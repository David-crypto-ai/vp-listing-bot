import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
WORKSHEET_NAME = os.environ["WORKSHEET_NAME"]

# --- MASTER SCHEMA (bot controlled) ---
BASE_SCHEMA = [
    "FECHA_CREACION_ITEM",
    "ITEM_ID",
    "ESTADO_ITEM",
    "FINDER_WORKER_ID",
    "RAW_CAPTION",
    "PARSE_CONFIDENCE",
    "PHOTO_COUNT"
]

# ---------------- USERS TABLE ----------------
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
        sheet = spreadsheet.worksheet("USERS")
    except:
        sheet = spreadsheet.add_worksheet(title="USERS", rows="1000", cols="10")
        sheet.append_row(USERS_SCHEMA)

    return sheet


def user_exists(user_id):
    sheet = get_users_sheet()
    data = sheet.get_all_values()
    for row in data[1:]:
        if row[0] == str(user_id) and row[4] == "ACTIVE":
            return True
    return False


def add_pending_user(user):
    sheet = get_users_sheet()

    sheet.append_row([
        str(user.id),
        user.username or "",
        user.full_name,
        "NONE",
        "PENDING",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ])

# ---------------- CONNECT ----------------
def get_sheet():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    sheet = spreadsheet.worksheet(WORKSHEET_NAME)

    ensure_schema(sheet)
    return sheet


# ---------------- SCHEMA CONTROL ----------------
def ensure_schema(sheet):
    existing = sheet.row_values(1)

    if not existing:
        sheet.append_row(BASE_SCHEMA)
        print("Schema initialized")
        return

    missing = [col for col in BASE_SCHEMA if col not in existing]

    if missing:
        updated = existing + missing
        sheet.update("1:1", [updated])
        print("Schema updated")


# ---------------- ID GENERATOR ----------------
def next_item_id(sheet):
    rows = sheet.get_all_values()
    count = len(rows)
    return f"VP-{count:06d}"


# ---------------- FIRST RECORD ----------------
def create_draft(worker_id="SYSTEM", caption="INIT"):
    sheet = get_sheet()

    item_id = next_item_id(sheet)

    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        item_id,
        "DRAFT",
        worker_id,
        caption,
        "0",
        "0"
    ]

    sheet.append_row(row)
    print("Draft created:", item_id)
