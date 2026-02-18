import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

USERS_TAB = "USERS"

USERS_SCHEMA = [
    "TELEGRAM_ID",
    "USERNAME",
    "FULL_NAME",
    "ROLE",
    "STATUS",
    "REGISTER_DATE"
]

def get_users_sheet():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        sheet = spreadsheet.worksheet(USERS_TAB)
    except:
        sheet = spreadsheet.add_worksheet(title=USERS_TAB, rows="1000", cols="20")
        sheet.append_row(USERS_SCHEMA)

    return sheet


def register_user(telegram_id, username, full_name):
    sheet = get_users_sheet()
    rows = sheet.get_all_values()

    for row in rows:
        if row and row[0] == telegram_id:
            return  # already registered

    sheet.append_row([
        telegram_id,
        username,
        full_name,
        "PENDING",
        "WAIT_APPROVAL",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ])
