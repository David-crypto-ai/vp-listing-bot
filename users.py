import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import SPREADSHEET_ID, GOOGLE_CREDENTIALS, WORKSHEET_USERS, ADMIN_IDS
from utils import now_str, safe_text

USERS_SCHEMA = [
    "TELEGRAM_ID",
    "USERNAME",
    "FULL_NAME",
    "ROLE",          # FINDER / SELLER / BOTH / GATEKEEPER / ADMIN
    "STATUS",        # PENDING / ACTIVE / BLOCKED
    "REGISTER_DATE",
    "APPROVED_BY",
    "APPROVED_AT"
]

def _client():
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def _sheet():
    ss = _client().open_by_key(SPREADSHEET_ID)
    try:
        sh = ss.worksheet(WORKSHEET_USERS)
    except Exception:
        sh = ss.add_worksheet(title=WORKSHEET_USERS, rows="2000", cols="20")
        sh.append_row(USERS_SCHEMA)
    # Ensure header
    header = sh.row_values(1)
    if not header:
        sh.append_row(USERS_SCHEMA)
    return sh

def get_user_row(telegram_id: str):
    sh = _sheet()
    rows = sh.get_all_values()
    for i, r in enumerate(rows[1:], start=2):
        if r and r[0] == str(telegram_id):
            return i, r
    return None, None

def register_user_pending(telegram_id: str, username: str, full_name: str):
    telegram_id = str(telegram_id)
    username = safe_text(username)
    full_name = safe_text(full_name)

    sh = _sheet()
    row_i, row = get_user_row(telegram_id)
    if row_i:
        # already exists; keep as-is
        return

    sh.append_row([
        telegram_id,
        username,
        full_name,
        "",            # ROLE empty until admin assigns
        "PENDING",
        now_str(),
        "",
        ""
    ])

def set_user_active_role(telegram_id: str, role: str, approved_by: str):
    sh = _sheet()
    row_i, row = get_user_row(str(telegram_id))
    if not row_i:
        return False

    # columns are 1-based:
    # ROLE=4, STATUS=5, APPROVED_BY=7, APPROVED_AT=8
    sh.update_cell(row_i, 4, role)
    sh.update_cell(row_i, 5, "ACTIVE")
    sh.update_cell(row_i, 7, str(approved_by))
    sh.update_cell(row_i, 8, now_str())
    return True

def set_user_blocked(telegram_id: str, approved_by: str):
    sh = _sheet()
    row_i, row = get_user_row(str(telegram_id))
    if not row_i:
        return False
    sh.update_cell(row_i, 5, "BLOCKED")
    sh.update_cell(row_i, 7, str(approved_by))
    sh.update_cell(row_i, 8, now_str())
    return True

def get_user_status_role(telegram_id: str):
    row_i, r = get_user_row(str(telegram_id))
    if not r:
        return None, "PENDING"
    role = (r[3] or "").strip()
    status = (r[4] or "PENDING").strip()
    return role, status

def is_admin(telegram_id: str) -> bool:
    return str(telegram_id) in ADMIN_IDS

def pending_users(limit=20):
    sh = _sheet()
    rows = sh.get_all_values()[1:]
    out = []
    for r in rows:
        if len(r) >= 5 and (r[4] == "PENDING"):
            out.append(r)
    return out[:limit]

def approval_keyboard(target_user_id: str):
    # Admin chooses role immediately after approval
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Approve as FINDER", callback_data=f"APPROVE|{target_user_id}|FINDER"),
            InlineKeyboardButton("Approve as SELLER", callback_data=f"APPROVE|{target_user_id}|SELLER"),
        ],
        [
            InlineKeyboardButton("Approve as BOTH", callback_data=f"APPROVE|{target_user_id}|BOTH"),
            InlineKeyboardButton("Approve as GATEKEEPER", callback_data=f"APPROVE|{target_user_id}|GATEKEEPER"),
        ],
        [
            InlineKeyboardButton("Approve as ADMIN", callback_data=f"APPROVE|{target_user_id}|ADMIN"),
            InlineKeyboardButton("Reject", callback_data=f"REJECT|{target_user_id}"),
        ]
    ])

async def notify_admin_new_user(context, telegram_id: str, username: str, full_name: str):
    # Sends an approval request to ALL admins
    if not ADMIN_IDS:
        return
    text = (
        "🧑‍💼 New user request\n\n"
        f"Name: {full_name}\n"
        f"Username: @{username if username else '(none)'}\n"
        f"ID: {telegram_id}\n\n"
        "Choose approval role:"
    )
    kb = approval_keyboard(str(telegram_id))
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text, reply_markup=kb)
        except Exception:
            pass
async def register_user(update, context):
    user = update.effective_user
    telegram_id = str(user.id)
    username = user.username or ""
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

    role, status = get_user_status_role(telegram_id)

    # ---------------- ADMIN AUTO-BOOTSTRAP ----------------
    if is_admin(telegram_id):
        # ensure exists
        register_user_pending(telegram_id, username, full_name)
        set_user_active_role(telegram_id, "ADMIN", telegram_id)
        return "ADMIN"

    # ---------------- EXISTING USER ----------------
    if role and status == "ACTIVE":
        return role

    # ---------------- NEW USER ----------------
    if not role:
        register_user_pending(telegram_id, username, full_name)
        await notify_admin_new_user(context, telegram_id, username, full_name)
        return "PENDING"

    # ---------------- WAITING APPROVAL ----------------
    return "PENDING"
def ensure_admin(telegram_id: str, username: str, full_name: str):
    telegram_id = str(telegram_id)
    sh = _sheet()
    row_i, row = get_user_row(telegram_id)

    if telegram_id not in ADMIN_IDS:
        return False

    if not row_i:
        sh.append_row([
            telegram_id,
            username,
            full_name,
            "ADMIN",
            "ACTIVE",
            now_str(),
            telegram_id,
            now_str()
        ])
        return True

    # if exists but pending → upgrade
    sh.update_cell(row_i, 4, "ADMIN")
    sh.update_cell(row_i, 5, "ACTIVE")
    sh.update_cell(row_i, 7, telegram_id)
    sh.update_cell(row_i, 8, now_str())
    return True
