import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

SERVICE_ACCOUNT_FILE = 'credentials.json'

credentials = Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES
)

gc = gspread.authorize(credentials)

def write_structured_data(spreadsheet_id: str, json_data: dict):
    name = json_data.get("相談者情報", {}).get("氏名", "無名")
    sheet_title = name if name else "無名"

    spreadsheet = gc.open_by_key(spreadsheet_id)

    try:
        spreadsheet.add_worksheet(title=sheet_title, rows="50", cols="10")
    except Exception as e:
        print(f"⚠️ シート '{sheet_title}' の作成に失敗または既に存在します: {e}")
        return

    worksheet = spreadsheet.worksheet(sheet_title)

    table_data = []
    for section, fields in json_data.items():
        table_data.append([section])
        for key, value in fields.items():
            table_data.append([key, value])
        table_data.append([])

    worksheet.update('A1', table_data)
    print(f"✅ シート '{sheet_title}' に構造化データを書き込みました。")
    return sheet_title  # シート名を返す（相談者名）

def is_user_registered(spreadsheet_id, user_id):
    sheet = gc.open_by_key(spreadsheet_id).worksheet("members")
    users = sheet.col_values(1)
    return user_id in users

def get_member_info(spreadsheet_id, user_id):
    """
    user_id に対応する登録メンバー情報を辞書で返す。
    """
    sheet = gc.open_by_key(spreadsheet_id).worksheet("members")
    all_rows = sheet.get_all_values()
    for row in all_rows[1:]:  # ヘッダーを除く
        if row[0] == user_id:
            return {
                "user_id": row[0],
                "office": row[1],
                "address": row[2],
                "role": row[3],
                "name": row[4]
            }
    return None

def register_user(spreadsheet_id, user_id, office, address, role, name):
    sheet = gc.open_by_key(spreadsheet_id).worksheet("members")
    sheet.append_row([user_id, office, address, role, name])

def log_individual_use(spreadsheet_id, user_id, name):
    try:
        sheet = gc.open_by_key(spreadsheet_id).worksheet("logs")
    except:
        spreadsheet = gc.open_by_key(spreadsheet_id)
        sheet = spreadsheet.add_worksheet(title="logs", rows="1000", cols="5")
        sheet.append_row(["user_id", "name", "timestamp"])

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([user_id, name, timestamp])
    print(f"📝 一般利用ログを記録: {user_id}, {name}, {timestamp}")

def log_request(spreadsheet_id, member_info, patient_name):
    """
    依頼者による相談受付のログを 'requests' シートに記録。
    """
    try:
        sheet = gc.open_by_key(spreadsheet_id).worksheet("requests")
    except:
        spreadsheet = gc.open_by_key(spreadsheet_id)
        sheet = spreadsheet.add_worksheet(title="requests", rows="1000", cols="6")
        sheet.append_row(["timestamp", "user_id", "事業所名", "氏名", "役職", "相談者氏名"])

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([
        timestamp,
        member_info.get("user_id", ""),
        member_info.get("office", ""),
        member_info.get("name", ""),
        member_info.get("role", ""),
        patient_name
    ])
    print(f"📌 依頼ログを記録: {member_info.get('name')} → {patient_name}（{timestamp}）")
