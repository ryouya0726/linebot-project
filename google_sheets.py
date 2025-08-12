import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from typing import Dict, Any, Optional

# =========================
# Google Sheets 認証設定
# =========================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SERVICE_ACCOUNT_FILE = "credentials.json"

credentials = Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES,
)
gc = gspread.authorize(credentials)


# =========================
# ユーティリティ
# =========================
def _ensure_worksheet(spreadsheet, title: str, rows="1000", cols="26"):
    """指定タイトルのワークシートがなければ作成して返す。あれば既存を返す。"""
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def _timestamp_str() -> str:
    """依頼日時フォーマット（例: 20250809_1430）"""
    return datetime.now().strftime("%Y%m%d_%H%M")


def _resolve_patient_name(json_data: Dict[str, Any]) -> str:
    """患者名の取り出しに幅を持たせる（新フォーマット対応）"""
    return (
        (json_data.get("患者情報", {}) or {}).get("氏名")    # ★ 追加：新しい構造
        or (json_data.get("相談者情報", {}) or {}).get("氏名") # 旧構造の互換
        or json_data.get("患者名")
        or "無名"
    )


# =========================
# メイン機能
# =========================
def write_structured_data(spreadsheet_id: str, user_id: Optional[str], json_data: Dict[str, Any]) -> str:
    """
    構造化データを指定スプレッドシートに表形式で書き込む。
    - シート名は「患者名_YYYYMMDD」に統一（同名があれば _HHMM を付与）
    - user_id があれば members シートから登録者情報を取得し、json_data に追加
    - requests シートに依頼ログも記録
    - 戻り値: 実際に作成したシート名
    """
    spreadsheet = gc.open_by_key(spreadsheet_id)

    # 登録者情報を追加
    if user_id:
        member_info = get_member_info(spreadsheet_id, user_id)
        if member_info:
            json_data["登録者情報"] = member_info
        else:
            print(f"⚠️ user_id {user_id} は members に未登録")

    # 患者名 & 依頼日(YYYYMMDD)
    base_name = _resolve_patient_name(json_data)
    req_date = datetime.now().strftime("%Y%m%d")
    sheet_title = f"{base_name}_{req_date}" if base_name else f"無名_{req_date}"

    # 同名回避：存在したら _HHMM を付けて再作成
    try:
        worksheet = spreadsheet.add_worksheet(title=sheet_title, rows="50", cols="10")
    except Exception as e:
        print(f"⚠️ シート '{sheet_title}' の作成に失敗または既に存在: {e}")
        existing_titles = [ws.title for ws in spreadsheet.worksheets()]
        if sheet_title in existing_titles:
            hhmm = datetime.now().strftime("%H%M")
            sheet_title = f"{sheet_title}_{hhmm}"
            worksheet = spreadsheet.add_worksheet(title=sheet_title, rows="50", cols="10")
            print(f"🆕 同名のため '{sheet_title}' を新規作成しました。")
        else:
            raise

    # 表形式に変換して書き込み
    table_data = []
    if all(isinstance(v, dict) for v in json_data.values()):
        for section, fields in json_data.items():
            table_data.append([section])
            for key, value in fields.items():
                table_data.append([key, value])
            table_data.append([])
    else:
        table_data.append(["データ"])
        for k, v in json_data.items():
            table_data.append([k, v])

    worksheet.update("A1", table_data)
    print(f"✅ シート '{sheet_title}' に構造化データを書き込みました。")

    # 依頼ログも記録
    if user_id:
        member_info = get_member_info(spreadsheet_id, user_id) or {}
        log_request(spreadsheet_id, member_info, base_name or "無名")

    return sheet_title

# =========================
# 会員・ログ関連
# =========================
def _ensure_members_sheet(spreadsheet_id: str):
    spreadsheet = gc.open_by_key(spreadsheet_id)
    sheet = _ensure_worksheet(spreadsheet, "members", rows="1000", cols="5")
    values = sheet.get_all_values()
    if not values:
        sheet.append_row(["user_id", "office", "address", "role", "name"])
    return sheet


def is_user_registered(spreadsheet_id: str, user_id: str) -> bool:
    try:
        sheet = _ensure_members_sheet(spreadsheet_id)
        users = sheet.col_values(1)
        return user_id in users
    except Exception as e:
        print("is_user_registered 失敗:", e)
        return False


def get_member_info(spreadsheet_id: str, user_id: str) -> Optional[Dict[str, str]]:
    try:
        sheet = _ensure_members_sheet(spreadsheet_id)
        all_rows = sheet.get_all_values()
        for row in all_rows[1:]:
            if row and row[0] == user_id:
                def _v(i): return row[i] if len(row) > i else ""
                return {
                    "user_id": _v(0),
                    "office": _v(1),
                    "address": _v(2),
                    "role": _v(3),
                    "name": _v(4),
                }
    except Exception as e:
        print("get_member_info 失敗:", e)
    return None


def register_user(spreadsheet_id: str, user_id: str, office: str, address: str, role: str, name: str):
    sheet = _ensure_members_sheet(spreadsheet_id)
    sheet.append_row([user_id, office, address, role, name])
    print(f"✅ members に登録: {user_id}, {office}, {address}, {role}, {name}")


def update_member_info(spreadsheet_id: str, user_id: str, updates: Dict[str, str]) -> bool:
    """
    membersシートの既存行を上書き更新する。
    updatesに含まれるキーだけ更新し、空欄は既存値を保持。
    """
    try:
        sheet = _ensure_members_sheet(spreadsheet_id)
        all_rows = sheet.get_all_values()
        for idx, row in enumerate(all_rows[1:], start=2):  # ヘッダーを飛ばして2行目から
            if row and row[0] == user_id:
                current = {
                    "user_id": row[0],
                    "office": row[1] if len(row) > 1 else "",
                    "address": row[2] if len(row) > 2 else "",
                    "role": row[3] if len(row) > 3 else "",
                    "name": row[4] if len(row) > 4 else "",
                }
                for k, v in updates.items():
                    if k in current and v:
                        current[k] = v
                sheet.update(f"A{idx}:E{idx}", [[
                    current["user_id"],
                    current["office"],
                    current["address"],
                    current["role"],
                    current["name"]
                ]])
                print(f"🔄 members更新: {current}")
                return True
        print(f"⚠️ user_id {user_id} がmembersに見つかりません")
        return False
    except Exception as e:
        print("update_member_info 失敗:", e)
        return False


def _ensure_logs_sheet(spreadsheet_id: str):
    spreadsheet = gc.open_by_key(spreadsheet_id)
    sheet = _ensure_worksheet(spreadsheet, "logs", rows="2000", cols="5")
    values = sheet.get_all_values()
    if not values:
        sheet.append_row(["user_id", "name", "timestamp"])
    return sheet


def log_individual_use(spreadsheet_id: str, user_id: str, name: str):
    try:
        sheet = _ensure_logs_sheet(spreadsheet_id)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([user_id, name, timestamp])
        print(f"📝 一般利用ログを記録: {user_id}, {name}, {timestamp}")
    except Exception as e:
        print("log_individual_use 失敗:", e)


def _ensure_requests_sheet(spreadsheet_id: str):
    spreadsheet = gc.open_by_key(spreadsheet_id)
    sheet = _ensure_worksheet(spreadsheet, "requests", rows="2000", cols="6")
    values = sheet.get_all_values()
    if not values:
        sheet.append_row(["timestamp", "user_id", "事業所名", "氏名", "役職", "相談者氏名"])
    return sheet


def log_request(spreadsheet_id: str, member_info: Dict[str, str], patient_name: str):
    """依頼者による相談受付のログを 'requests' シートに記録"""
    try:
        sheet = _ensure_requests_sheet(spreadsheet_id)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([
            timestamp,
            member_info.get("user_id", ""),
            member_info.get("office", ""),
            member_info.get("name", ""),
            member_info.get("role", ""),
            patient_name,
        ])
        print(f"📌 依頼ログ: {member_info.get('name')} → {patient_name}（{timestamp}）")
    except Exception as e:
        print("log_request 失敗:", e)

def format_member_info(member_info: Dict[str, str]) -> str:
    """
    人間が見やすい形に整形した登録者情報を返す
    """
    if not member_info:
        return "登録情報は見つかりませんでした。"

    lines = [
        "📋【登録者情報】",
        f"氏名：{member_info.get('name', '')}",
        f"事業所名：{member_info.get('office', '')}",
        f"住所：{member_info.get('address', '')}",
        f"役職：{member_info.get('role', '')}",
        f"ユーザーID：{member_info.get('user_id', '')}",
    ]
    return "\n".join(lines)
