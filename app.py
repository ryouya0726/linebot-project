from flask import Flask, request
import os, json, logging
from dotenv import load_dotenv

# ===== LINE v3 SDK =====
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage as V3TextMessage,
)
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# ===== Google Sheets 側ユーティリティ =====
from google_sheets import (
    is_user_registered,
    register_user,
    write_structured_data,
    get_member_info,
    format_member_info,
)

# ===== 質問管理 =====
from chatgpt_processor import ConversationManager
cm = ConversationManager("questions.json")

# ==============================
# 初期設定
# ==============================
load_dotenv()
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# v3 初期化
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
api_client = ApiClient(configuration)
messaging_api = MessagingApi(api_client)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# セッション: user_id -> dict
user_sessions = {}
MAX_CONFIRM_RETRIES = 3

# ==============================
# 質問読み込み（"field" でも "key" でもOKに正規化）
# ==============================
def _load_questions(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    normalized = []
    for q in raw:
        fld = q.get("field") or q.get("key")
        normalized.append({"field": fld, "question": q["question"]})
    return normalized

CONSULT_QUESTIONS = _load_questions("questions.json")
REGISTER_QUESTIONS = _load_questions("register_questions.json")

# ==============================
# 送信ラッパ（落ちにくく）
# ==============================
def safe_reply(reply_token: str, text: str):
    try:
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[V3TextMessage(text=text)]
            )
        )
    except Exception as e:
        app.logger.error(f"Reply failed: {e}")

# ==============================
# 確認用プレビュー
# ==============================
def _format_register_preview(answers: dict) -> str:
    office = answers.get("office", "")
    address = answers.get("address", "")
    role = answers.get("role", "")
    name = answers.get("name", "")
    return (
        "📋【登録者情報の確認】\n"
        f"・氏名：{name}\n"
        f"・事業所名：{office}\n"
        f"・住所：{address}\n"
        f"・役職：{role}\n\n"
        "この内容で登録します。よろしいですか？（はい / いいえ）"
    )

# 27項目の日本語ラベル（相談内容プレビュー用）
_LABEL_MAP = {
    "furigana": "ふりがな",
    "patient_name": "氏名",
    "gender": "性別",
    "dob": "生年月日",
    "age": "年齢",
    "address": "住所（施設名含む）",
    "postal_code": "郵便番号",
    "home_phone": "電話（自宅）",
    "mobile_phone": "電話（携帯）",
    "emergency_contact": "緊急連絡先電話番号",
    "parking": "駐車場",
    "residence_type": "居住形態",
    "care_level": "要介護度",
    "medical_history": "既往歴",
    "current_condition": "現病歴",
    "infection_status": "感染症",
    "internal_medicine_hospital": "内科主治医_病院名",
    "internal_medicine_doctor": "内科主治医_医師名",
    "communication_ability": "意思疎通",
    "swallowing_function": "嚥下機能",
    "medication_status": "服薬状況",
    "onset_date": "発症日・発症年",
    "preferred_visit_time": "希望訪問曜日・時間帯",
    "accompanying_person": "同席者",
    "key_person_name": "キーパーソン_氏名",
    "key_person_relationship": "キーパーソン_続柄",
    "key_person_address": "キーパーソン_住所",
}

def _format_consult_preview(answers: dict) -> str:
    lines = ["🧑‍⚕️【患者さま情報の確認】"]
    for q in CONSULT_QUESTIONS:
        key = q["field"]
        val = answers.get(key, "")
        if val:
            label = _LABEL_MAP.get(key, key)
            lines.append(f"・{label}：{val}")
    lines.append("\nこの内容でよろしいですか？（はい / いいえ）")
    return "\n".join(lines)

# ==============================
# 構造化変換（chatgpt_processorに委譲）
# ==============================
def _answers_to_structured_json(answers: dict) -> dict:
    return cm.build_structured_json(answers)

# ==============================
# Healthチェック
# ==============================
@app.route("/healthz", methods=["GET"])
def healthz():
    return "ok", 200

# ==============================
# Webhook（必ず200を返す）
# ==============================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")
    try:
        handler.handle(body, signature or "")
    except Exception as e:
        app.logger.error(f"Webhook error: {e}")
        return "OK", 200
    return "OK", 200

# ==============================
# メッセージ処理
# ==============================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    try:
        user_id = event.source.user_id
        text = (event.message.text or "").strip()

        ses = user_sessions.get(user_id) or {
            "mode": None,
            "step": 0,
            "answers": {},
            "phase": None,      # None | confirm_register | confirm_consult
            "retry": 0,
        }
        user_sessions[user_id] = ses

        # 共通
        if text in ["キャンセル", "中止", "やめる"]:
            user_sessions.pop(user_id, None)
            safe_reply(event.reply_token, "中止しました。")
            return

        # フロー開始
        if text in ["登録する", "登録したい"]:
            ses.update({"mode": "register", "step": 0, "answers": {}, "phase": None, "retry": 0})
            safe_reply(event.reply_token, REGISTER_QUESTIONS[0]["question"])
            return

        if text in ["依頼する", "依頼したい", "相談したい"]:
            if not is_user_registered(SPREADSHEET_ID, user_id):
                ses.update({"mode": "register", "step": 0, "answers": {}, "phase": None, "retry": 0})
                safe_reply(event.reply_token, "まず、依頼者情報の登録をお願いします。")
                safe_reply(event.reply_token, REGISTER_QUESTIONS[0]["question"])
                return
            # すでに登録済みなら、登録内容の再確認 → OKなら相談へ
            ses.update({"mode": "register", "step": 0, "phase": "confirm_register", "retry": 0, "answers": {}})
            mi = get_member_info(SPREADSHEET_ID, user_id) or {}
            preview = format_member_info(mi) + "\n\nこの登録情報でよろしいですか？（はい / いいえ）"
            safe_reply(event.reply_token, preview)
            return

        # ===== 登録の入力フェーズ =====
        if ses["mode"] == "register" and ses["phase"] is None:
            q = REGISTER_QUESTIONS[ses["step"]]
            field = q["field"]
            ses["answers"][field] = text

            if ses["step"] + 1 < len(REGISTER_QUESTIONS):
                ses["step"] += 1
                safe_reply(event.reply_token, REGISTER_QUESTIONS[ses["step"]]["question"])
                return

            # 入力終わり → 人間が見やすい確認へ
            ses["phase"] = "confirm_register"
            ses["retry"] = 0
            safe_reply(event.reply_token, _format_register_preview(ses["answers"]))
            return

        # ===== 登録の確認フェーズ =====
        if ses["phase"] == "confirm_register":
            lower = text.lower()
            if lower in ["はい", "ok", "yes", "はい。", "うん"]:
                # 新規登録 or 既存をOKして進む
                if ses["mode"] == "register" and ses["answers"]:
                    try:
                        register_user(
                            SPREADSHEET_ID,
                            user_id,
                            ses["answers"].get("office", ""),
                            ses["answers"].get("address", ""),
                            ses["answers"].get("role", ""),
                            ses["answers"].get("name", ""),
                        )
                        safe_reply(event.reply_token, "✅ 登録が完了しました。次に患者さま情報を伺います。")
                    except Exception as e:
                        app.logger.error(f"register_user error: {e}")
                        safe_reply(event.reply_token, "大変申し訳御座いませんが、070-1689-2637まで、お電話ください。")
                        user_sessions.pop(user_id, None)
                        return

                # 相談へ
                ses.update({"mode": "consult", "step": 0, "phase": None, "retry": 0, "answers": {}})
                safe_reply(event.reply_token, CONSULT_QUESTIONS[0]["question"])
                return

            elif lower in ["いいえ", "no", "いや", "変更", "修正"]:
                ses["retry"] += 1
                if ses["retry"] >= MAX_CONFIRM_RETRIES:
                    safe_reply(event.reply_token, "大変申し訳御座いませんが、070-1689-2637まで、お電話ください。")
                    user_sessions.pop(user_id, None)
                    return
                # 入力からやり直し
                ses.update({"mode": "register", "step": 0, "phase": None})
                safe_reply(event.reply_token, "登録情報を修正します。はじめから伺います。")
                safe_reply(event.reply_token, REGISTER_QUESTIONS[0]["question"])
                return

            else:
                ses["retry"] += 1
                if ses["retry"] >= MAX_CONFIRM_RETRIES:
                    safe_reply(event.reply_token, "大変申し訳御座いませんが、070-1689-2637まで、お電話ください。")
                    user_sessions.pop(user_id, None)
                    return
                safe_reply(event.reply_token, "『はい』または『いいえ』でお答えください。")
                return

        # ===== 相談フロー（27項目） =====
        if ses["mode"] == "consult" and ses["phase"] is None:
            q = CONSULT_QUESTIONS[ses["step"]]
            field = q["field"]
            ses["answers"][field] = text

            if ses["step"] + 1 < len(CONSULT_QUESTIONS):
                ses["step"] += 1
                safe_reply(event.reply_token, CONSULT_QUESTIONS[ses["step"]]["question"])
                return

            # 最終確認へ
            ses["phase"] = "confirm_consult"
            ses["retry"] = 0
            safe_reply(event.reply_token, _format_consult_preview(ses["answers"]))
            return

        # ===== 相談の確認フェーズ =====
        if ses["phase"] == "confirm_consult":
            lower = text.lower()
            if lower in ["はい", "ok", "yes", "はい。", "うん"]:
                try:
                    data = _answers_to_structured_json(ses["answers"])
                    sheet_name = write_structured_data(SPREADSHEET_ID, user_id, data)
                    safe_reply(event.reply_token, f"✅ ありがとうございました。内容を記録しました。\n→ シート名：{sheet_name}")
                    user_sessions.pop(user_id, None)
                    return
                except Exception as e:
                    app.logger.error(f"write_structured_data error: {e}")
                    safe_reply(event.reply_token, "大変申し訳御座いませんが、070-1689-2637まで、お電話ください。")
                    user_sessions.pop(user_id, None)
                    return

            elif lower in ["いいえ", "no", "いや", "変更", "修正"]:
                ses["retry"] += 1
                if ses["retry"] >= MAX_CONFIRM_RETRIES:
                    safe_reply(event.reply_token, "大変申し訳御座いませんが、070-1689-2637まで、お電話ください。")
                    user_sessions.pop(user_id, None)
                    return
                safe_reply(event.reply_token, "修正したい項目と内容を『項目名 半角スペース 値』の形式で送ってください。\n例）氏名 佐藤花子")
                ses["phase"] = "edit_consult"
                return

            else:
                ses["retry"] += 1
                if ses["retry"] >= MAX_CONFIRM_RETRIES:
                    safe_reply(event.reply_token, "大変申し訳御座いませんが、070-1689-2637まで、お電話ください。")
                    user_sessions.pop(user_id, None)
                    return
                safe_reply(event.reply_token, "『はい』または『いいえ』でお答えください。")
                return

        # ===== 相談 修正入力 =====
        if ses["phase"] == "edit_consult":
            if " " in text:
                key, value = text.split(" ", 1)
                value = value.strip()
                # ラベル → key 変換（主要項目のみ対応）
                inv_map = {v: k for k, v in _LABEL_MAP.items()}
                mapped_key = inv_map.get(key, key)
                if mapped_key in ses["answers"]:
                    ses["answers"][mapped_key] = value
                    safe_reply(event.reply_token, f"『{key}』を『{value}』に修正しました。")
                    ses["phase"] = "confirm_consult"
                    ses["retry"] = 0
                    safe_reply(event.reply_token, _format_consult_preview(ses["answers"]))
                else:
                    safe_reply(event.reply_token, f"『{key}』という項目が見つかりませんでした。もう一度お試しください。")
                return
            else:
                safe_reply(event.reply_token, "『項目名 半角スペース 値』の形式で入力してください。")
                return

        # デフォルト
        safe_reply(
            event.reply_token,
            "次のいずれかを送ってください：\n"
            "・『依頼する』… 登録情報を確認→患者情報とご相談内容をお伺いします\n"
            "・『登録する』… 依頼者情報を登録/修正します\n"
            "・『キャンセル』… 途中で中止します"
        )

    except Exception as e:
        app.logger.error(f"Message handling error: {e}")
        safe_reply(event.reply_token, "大変申し訳御座いませんが、070-1689-2637まで、お電話ください。")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
