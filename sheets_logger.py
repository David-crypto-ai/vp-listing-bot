import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone, timedelta

from config import (
    SPREADSHEET_ID, GOOGLE_CREDENTIALS,
    WORKSHEET_ITEMS, WORKSHEET_OWNERS, WORKSHEET_LOG, WORKSHEET_TASKS,
    DAYS_CONFIRM_WINDOW, DAYS_AUTO_HIDE
)
from utils import now_str, fmt_item_id, safe_text, is_vin_17

# ---------------- SCHEMAS ----------------

ITEMS_SCHEMA = [
    # system
    "FECHA_CREACION_ITEM",
    "ITEM_ID",
    "ESTADO_ITEM",            # DRAFT / PENDING_REVIEW / ACTIVE / SOLD / HIDDEN
    "FINDER_WORKER_ID",
    "SELLER_WORKER_ID",
    "GATEKEEPER_ID",
    "LAST_UPDATED_AT",

    # raw intake
    "RAW_CAPTION",
    "PARSE_CONFIDENCE",
    "PHOTO_COUNT",

    # owner link
    "OWNER_ID",
    "OWNER_TYPE",             # Truck Owner / Online Owner / Auction Company
    "OWNER_NAME_CACHE",

    # public fields (minimal for now)
    "VIN_COMPLETO",
    "DESCRIPCION_PUBLICA",
    "UBICACION_PUBLICA",

    # pricing/admin
    "OWNER_PRICE",
    "LIST_PRICE",
    "COMMISSION_RATE",
    "COMMISSION_AMOUNT",
    "SELLER_COMMISSION_AMOUNT",
    "NET_TO_OWNER",

    # lifecycle confirmations
    "LAST_CONFIRMED_AVAILABLE_AT",
    "NEXT_CONFIRM_DUE_AT",
    "AUTO_HIDE_AT",

    # sold
    "SOLD_AT",
    "SOLD_PRICE",
    "SOLD_NOTES",

    # publishing placeholders (later)
    "SHOPIFY_PRODUCT_ID",
    "SHOPIFY_STATUS",
    "PUBLIC_TELEGRAM_MESSAGE_ID",
]

OWNERS_SCHEMA = [
    "OWNER_ID",
    "OWNER_TYPE",          # Truck Owner / Online Owner / Auction Company
    "OWNER_NAME",
    "OWNER_PHONE",
    "CITY_STATE",
    "SOURCE_PLATFORM",
    "SOURCE_LINK",
    "MAPS_LINK",
    "LOCATION_PHOTO_URL",
    "CLAIMED_BY_FINDER_ID",
    "OWNER_STATUS",        # PENDING / APPROVED / BLOCKED
    "APPROVED_BY",
    "CREATED_AT",
    "LAST_CONTACTED_AT",
    "NOTES",
]

LOG_SCHEMA = [
    "TIMESTAMP",
    "USER_ID",
    "ROLE_AT_TIME",
    "ACTION_TYPE",
    "ITEM_ID",
    "OWNER_ID",
    "DETAILS",
    "RESULT"
]

TASKS_SCHEMA = [
    "TASK_ID",
    "CREATED_AT",
    "CREATED_BY_USER_ID",
    "ASSIGNED_TO_USER_ID",
    "TASK_TYPE",          # FOLLOWUP / TODO
    "TITLE",
    "DESCRIPTION",
    "DUE_AT",
    "STATUS",             # OPEN / DONE / SNOOZED / RESCHEDULED
    "LAST_REMINDER_SENT_AT",
    "REMINDER_FREQUENCY_MIN",
    "RELATED_OWNER_ID",
    "RELATED_ITEM_ID"
]

# ---------------- CONNECT ----------------

def _client():
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def _get_ws(title: str, schema: list, rows="5000", cols="60"):
    ss = _client().open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet(title)
    except Exception:
        ws = ss.add_worksheet(title=title, rows=rows, cols=cols)
        ws.append_row(schema)
        return ws

    header = ws.row_values(1)
    if not header:
        ws.append_row(schema)
        return ws

    # add missing columns
    missing = [c for c in schema if c not in header]
    if missing:
        ws.update("1:1", [header + missing])
    return ws

def items_ws():
    return _get_ws(WORKSHEET_ITEMS, ITEMS_SCHEMA)

def owners_ws():
    return _get_ws(WORKSHEET_OWNERS, OWNERS_SCHEMA, cols="40")

def log_ws():
    return _get_ws(WORKSHEET_LOG, LOG_SCHEMA, cols="20")

def tasks_ws():
    return _get_ws(WORKSHEET_TASKS, TASKS_SCHEMA, cols="25")

# ---------------- LOGGING ----------------

def log_action(user_id: str, role: str, action: str, item_id="", owner_id="", details="", result="OK"):
    ws = log_ws()
    ws.append_row([
        now_str(),
        str(user_id),
        str(role),
        str(action),
        str(item_id),
        str(owner_id),
        safe_text(details),
        str(result)
    ])

# ---------------- OWNERS ----------------

def next_owner_id():
    ws = owners_ws()
    count = len(ws.get_all_values())  # includes header
    return f"OWN-{count:06d}"

def find_owner_matches(query: str, limit=10):
    q = safe_text(query).lower()
    ws = owners_ws()
    rows = ws.get_all_values()[1:]
    out = []
    for r in rows:
        name = (r[2] if len(r) > 2 else "").lower()
        phone = (r[3] if len(r) > 3 else "").lower()
        if q in name or q in phone:
            out.append(r)
    return out[:limit]

def create_owner(owner_type, name, phone, city_state, source_platform, source_link, maps_link, location_photo_url, claimed_by):
    ws = owners_ws()
    owner_id = next_owner_id()
    ws.append_row([
        owner_id,
        owner_type,
        name,
        phone,
        city_state,
        source_platform,
        source_link,
        maps_link,
        location_photo_url,
        str(claimed_by),
        "PENDING",      # gatekeeper/admin approves
        "",
        now_str(),
        "",
        ""
    ])
    return owner_id

def approve_owner(owner_id: str, approved_by: str):
    ws = owners_ws()
    rows = ws.get_all_values()
    for i, r in enumerate(rows[1:], start=2):
        if r and r[0] == owner_id:
            ws.update_cell(i, 11, "APPROVED")  # OWNER_STATUS
            ws.update_cell(i, 12, str(approved_by))
            return True
    return False

def get_owner(owner_id: str):
    ws = owners_ws()
    rows = ws.get_all_values()[1:]
    for r in rows:
        if r and r[0] == owner_id:
            return r
    return None

def owners_recent_for_user(user_id: str, limit=10):
    ws = owners_ws()
    rows = ws.get_all_values()[1:]
    out = []
    for r in reversed(rows):
        if len(r) > 9 and r[9] == str(user_id):
            out.append(r)
        if len(out) >= limit:
            break
    return out

# ---------------- ITEMS ----------------

def next_item_id():
    ws = items_ws()
    count = len(ws.get_all_values())  # includes header
    return fmt_item_id(count)

def create_draft(worker_id: str, owner_id: str, owner_type: str, owner_name_cache: str):
    ws = items_ws()
    item_id = next_item_id()
    now = now_str()

    # Confirmation windows
    next_due = (datetime.now(timezone.utc) + timedelta(days=DAYS_CONFIRM_WINDOW)).strftime("%Y-%m-%d %H:%M:%S")
    auto_hide = (datetime.now(timezone.utc) + timedelta(days=DAYS_AUTO_HIDE)).strftime("%Y-%m-%d %H:%M:%S")

    ws.append_row([
        now,
        item_id,
        "DRAFT",
        str(worker_id),
        "",        # seller
        "",        # gatekeeper
        now,

        "",        # raw_caption
        "0",
        "0",

        owner_id,
        owner_type,
        owner_name_cache,

        "",        # vin
        "",        # public desc
        "",        # public location

        "", "", "", "", "", "",

        "",        # last_confirmed
        next_due,
        auto_hide,

        "", "", "",

        "", "", ""
    ])
    return item_id

def get_item_row(item_id: str):
    ws = items_ws()
    rows = ws.get_all_values()
    header = rows[0]
    for i, r in enumerate(rows[1:], start=2):
        if r and r[1] == item_id:
            return ws, header, i, r
    return None, None, None, None

def update_item_fields(item_id: str, updates: dict):
    ws, header, row_i, row = get_item_row(item_id)
    if not row_i:
        return False

    # update LAST_UPDATED_AT always
    updates["LAST_UPDATED_AT"] = now_str()

    col_index = {name: idx+1 for idx, name in enumerate(header)}
    for k, v in updates.items():
        if k in col_index:
            ws.update_cell(row_i, col_index[k], str(v))
    return True

def list_items_by_status(status: str, limit=10, worker_id=None):
    ws = items_ws()
    rows = ws.get_all_values()[1:]
    out = []
    for r in reversed(rows):
        if len(r) < 3:
            continue
        if r[2] != status:
            continue
        if worker_id and len(r) > 3 and r[3] != str(worker_id):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out

def next_pending_review():
    ws = items_ws()
    rows = ws.get_all_values()[1:]
    # oldest first
    for r in rows:
        if len(r) > 2 and r[2] == "PENDING_REVIEW":
            return r
    return None

def validate_caption_vin(caption: str):
    # If vin present in caption in a simple way, you can improve later
    # For now: extract any 17-alnum token
    tokens = [t.strip().upper() for t in safe_text(caption).replace("\n", " ").split(" ")]
    for t in tokens:
        if is_vin_17(t):
            return t
    return ""

# ---------------- TASKS ----------------

def next_task_id():
    ws = tasks_ws()
    count = len(ws.get_all_values())
    return f"TASK-{count:06d}"

def create_task(created_by, assigned_to, task_type, title, description, due_at, related_owner_id="", related_item_id=""):
    ws = tasks_ws()
    task_id = next_task_id()
    ws.append_row([
        task_id,
        now_str(),
        str(created_by),
        str(assigned_to),
        task_type,
        title,
        description,
        due_at,
        "OPEN",
        "",
        "60",
        related_owner_id,
        related_item_id
    ])
    return task_id

def open_tasks_for_user(user_id: str, limit=15):
    ws = tasks_ws()
    rows = ws.get_all_values()[1:]
    out = []
    for r in rows:
        if len(r) > 8 and r[3] == str(user_id) and r[8] == "OPEN":
            out.append(r)
    return out[:limit]

def set_task_status(task_id: str, status: str):
    ws = tasks_ws()
    rows = ws.get_all_values()
    header = rows[0]
    idx = {h: i+1 for i, h in enumerate(header)}
    for i, r in enumerate(rows[1:], start=2):
        if r and r[0] == task_id:
            ws.update_cell(i, idx["STATUS"], status)
            return True
    return False

def set_task_last_reminder(task_id: str):
    ws = tasks_ws()
    rows = ws.get_all_values()
    header = rows[0]
    idx = {h: i+1 for i, h in enumerate(header)}
    for i, r in enumerate(rows[1:], start=2):
        if r and r[0] == task_id:
            ws.update_cell(i, idx["LAST_REMINDER_SENT_AT"], now_str())
            return True
    return False
