import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

SHEET_NAME = "VP_PRIVATE_INVENTORY"

def connect_sheet():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
    return sheet


def add_test_row():
    sheet = connect_sheet()
    sheet.append_row([
        "TEST",
        "PRUEBA",
        "0",
        "0",
        "0",
        "VIN123",
        "BOT",
        "000",
        "SISTEMA",
        datetime.now().strftime("%d/%m/%Y %H:%M"),
        "render"
    ])
