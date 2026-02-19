import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import SPREADSHEET_ID, GOOGLE_CREDENTIALS, ADMIN_IDS
from utils import now_str, safe_text


# ================================
# SHEET NAMES (NEW SYSTEM)
# ================================
TAB_USERS = "USERS"
TAB_ROLES = "USER_ROLES"
TAB_PERMS = "USER_PERMISSIONS"


# ================================
# GOOGLE CLIENT
# ================================
def _client():
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)


def _worksheet(name, headers):
    ss = _client().open_by_key(SPREADSHEET_ID)
    try:
        sh = ss.worksheet(name)
    except Exception:
        sh = ss.add_worksheet(title=name, rows="2000", cols="20")
        sh.append_row(headers)

    if not sh.row_values(1):
        sh.append_row(headers)

    return sh


def users_sheet():
    return _worksheet(TAB_USERS,
        ["TELEGRAM_ID","USERNAME","FULL_NAME","STATUS","CREATED_AT","LAST_SEEN"]
    )


def roles_sheet():
    return _worksheet(TAB_ROLES,
        ["TELEGRAM_ID","ROLE","ASSIGNED_BY","ASSIGNED_AT"]
    )


def perms_sheet():
    return _worksheet(TAB_PERMS,
        ["TELEGRAM_ID","PERMISSION","GRANTED_BY","GRANTED_AT"]
    )


# ================================
# USER LOOKUP
# ================================
def find_user(telegram_id):
    sh = users_sheet()
    rows = sh.get_all_values()

    for i, r in enumerate(rows[1:], start=2):
        if r and r[0] == str(telegram_id):
            return i, r
    return None, None


# ================================
# REGISTER USER
# ================================
def register_user_pending(telegram_id, username, full_name):
    telegram_id = str(telegram_id)
    username = safe_text(username)
    full_name = safe_text(full_name)

    sh = users_sheet()
    row_i, _ = find_user(telegram_id)

    # already exists
    if row_i:
        return False

    sh.append_row([
        telegram_id,
        username,
        full_name,
        "PENDING",
        now_str(),
        now_str()
    ])

    return True


# ================================
# ROLE MANAGEMENT
# ================================
def assign_role(telegram_id, role, admin_id):
    telegram_id = str(telegram_id)
    role = str(role)

    sh = roles_sheet()

    # 🚫 prevent duplicate roles
    existing_roles = get_user_roles(telegram_id)
    if role in existing_roles:
        return

    sh.append_row([telegram_id, role, admin_id, now_str()])

    # activate user
    u_sh = users_sheet()
    row_i, _ = find_user(telegram_id)
    if row_i:
        u_sh.update_cell(row_i, 4, "ACTIVE")


def get_user_roles(telegram_id):
    sh = roles_sheet()
    rows = sh.get_all_values()[1:]
    return [r[1] for r in rows if r[0] == str(telegram_id)]


# ================================
# PERMISSIONS
# ================================
def grant_permission(telegram_id, perm, admin_id):
    sh = perms_sheet()
    sh.append_row([telegram_id, perm, admin_id, now_str()])


def get_user_permissions(telegram_id):
    sh = perms_sheet()
    rows = sh.get_all_values()[1:]
    return [r[1] for r in rows if r[0] == str(telegram_id)]


# ================================
# STATUS + ROLE (compatibility)
# ================================
def get_user_status_role(telegram_id):
    telegram_id = str(telegram_id)

    row_i, r = find_user(telegram_id)
    if not r:
        return None, "PENDING"

    # 🔄 update last seen every interaction
    try:
        users_sheet().update_cell(row_i, 6, now_str())
    except Exception:
        pass

    status = r[3]
    roles = get_user_roles(telegram_id)

    if not roles:
        return None, status

    # temporary compatibility with old menu system
    if "ADMIN" in roles:
        return "ADMIN", status
    if "GATEKEEPER" in roles:
        return "GATEKEEPER", status
    if "FINDER" in roles and "SELLER" in roles:
        return "BOTH", status
    if "FINDER" in roles:
        return "FINDER", status
    if "SELLER" in roles:
        return "SELLER", status

    return None, status


# ================================
# ADMIN AUTO-BOOTSTRAP
# ================================
def ensure_admin(telegram_id, username, full_name):
    telegram_id = str(telegram_id)

    if telegram_id not in ADMIN_IDS:
        return False

    register_user_pending(telegram_id, username, full_name)

    roles = get_user_roles(telegram_id)
    if "ADMIN" not in roles:
        assign_role(telegram_id, "ADMIN", telegram_id)

    perms = [
        "VIEW_ALL_PRICES",
        "EDIT_OWNER_PRICE",
        "EDIT_FINAL_PRICE",
        "MANAGE_USERS",
        "ASSIGN_ROLES"
    ]

    existing = get_user_permissions(telegram_id)
    for p in perms:
        if p not in existing:
            grant_permission(telegram_id, p, telegram_id)

    return True

# ================================
# ADMIN NOTIFICATION (APPROVAL PANEL)
# ================================
async def notify_admin_new_user(context, telegram_id, username, full_name):

    text = (
        "👤 *New User Request*\n\n"
        f"ID: `{telegram_id}`\n"
        f"Username: @{username if username else 'none'}\n"
        f"Name: {full_name}\n\n"
        "Choose role:"
    )

    keyboard = [
        [
            InlineKeyboardButton("Finder", callback_data=f"APPROVE|{telegram_id}|FINDER"),
            InlineKeyboardButton("Seller", callback_data=f"APPROVE|{telegram_id}|SELLER"),
        ],
        [
            InlineKeyboardButton("Both", callback_data=f"APPROVE|{telegram_id}|BOTH"),
            InlineKeyboardButton("Gatekeeper", callback_data=f"APPROVE|{telegram_id}|GATEKEEPER"),
        ],
        [
            InlineKeyboardButton("❌ Reject", callback_data=f"REJECT|{telegram_id}")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception:
            pass
