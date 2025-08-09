from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

from google_sheets import write_structured_data
import os
import json
from dotenv import load_dotenv

# 環境変数
load_dotenv()
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
app = Flask(__name__)

# セッション管理用辞書
user_session_state = {}

# 質問リスト読み込み
with open("questions.json", "r", encoding="utf-8") as f:
    questions = json.load(f)

def send_reply(reply_token, text):
    line_bot_api.reply_message(reply_token, TextSendMessage(text=text))

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent)
def handle_message(event):
    if not isinstance(event.message, TextMessage):
        return

    user_id = event.source.user_id
    message = event.message.text.strip()

    # 会話スタート
    if message in ["依頼したい", "相談したい", "お願いしたい"]:
        user_session_state[user_id] = {"step": 0, "answers": {}}
        first_question = questions[0]["question"]
        send_reply(event.reply_token, first_question)
        return

    # 会話途中（セッションがある場合）
    if user_id in user_session_state:
        session = user_session_state[user_id]
        step = session["step"]
        answers = session["answers"]

        # 回答保存
        field_path = questions[step]["field"]
        # ネストされたキーに対応
        section, key = field_path.split(".")
        if section not in answers:
            answers[section] = {}
        answers[section][key] = message

        # 次の質問 or 完了
        if step + 1 < len(questions):
            session["step"] += 1
            next_question = questions[session["step"]]["question"]
            send_reply(event.reply_token, next_question)
        else:
            try:
                sheet_name = write_structured_data(SPREADSHEET_ID, answers)
                send_reply(event.reply_token, f"✅ ありがとうございました！内容を記録しました。\n→ シート名: {sheet_name}")
            except Exception as e:
                print("❌ 転記エラー:", e)
                send_reply(event.reply_token, "⚠️ データの保存中にエラーが発生しました。")
            # セッション終了
            del user_session_state[user_id]
        return

    # デフォルト応答
    send_reply(event.reply_token, "『依頼したい』と送っていただくと、順番に質問を開始します。")

if __name__ == "__main__":
    app.run(port=8000)
