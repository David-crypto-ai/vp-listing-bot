import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timezone, timedelta
import math

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
    "OWNER_EMAIL",
    "CITY_STATE",
    "SOURCE_PLATFORM",
    "SOURCE_LINK",
    "MAPS_LINK",
    "LOCATION_PHOTO_URL",   # stores Telegram file_id
    "CLAIMED_BY_FINDER_ID",
    "OWNER_STATUS",        # PENDING / APPROVED / BLOCKED
    "APPROVED_BY",
    "CREATED_AT",
    "LAST_CONTACTED_AT",
    "NOTES",
    "LOCATION_COORDS",
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
# ---------------- SCHEMA VALIDATION ----------------

def _validate_schema(ws, expected_schema, sheet_name):
    header = ws.row_values(1)

    if not header:
        raise Exception(f"❌ {sheet_name} has no header row.")

    # exact match required for safety
    if header[:len(expected_schema)] != expected_schema:
        raise Exception(
            f"""
❌ SCHEMA MISMATCH in {sheet_name}

Expected:
{expected_schema}

Found:
{header}

Fix the sheet header manually before running the bot.
"""
        )

_CLIENT = None

def _client():
    global _CLIENT

    if _CLIENT:
        return _CLIENT

    creds_dict = json.loads(GOOGLE_CREDENTIALS)

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)

    _CLIENT = gspread.authorize(creds)

    return _CLIENT

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

    # validate schema instead of modifying it
    _validate_schema(ws, schema, title)

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
# ---------------- DISTANCE CHECK ----------------

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2

    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))


def check_nearby_accounts(lat, lon, radius=120):
    ws = owners_ws()
    rows = ws.get_all_values()[1:]

    matches = []

    for r in rows:

        if len(r) < 17:
            continue

        coords = r[16]

        if not coords:
            continue

        try:
            lat2, lon2 = map(float, coords.split(","))
        except:
            continue

        dist = haversine_distance(lat, lon, lat2, lon2)

        if dist <= radius:
            matches.append((r, int(dist)))

    return matches

def next_owner_id():
    ws = owners_ws()
    rows = ws.get_all_values()[1:]
    return f"OWN-{len(rows)+1:06d}"

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

def create_owner_submission(
        submitted_by,
        coords,
        maps_link,
        photo_url,
        owner_name,
        owner_phone,
        owner_email,
        city_state,
        source_platform,
        source_link,
        distance_warning):

    ss = _client().open_by_key(SPREADSHEET_ID)

    try:
        ws = ss.worksheet("OWNER_SUBMISSIONS")
    except Exception:
        ws = ss.add_worksheet(title="OWNER_SUBMISSIONS", rows="5000", cols="20")

        ws.append_row([
            "SUBMISSION_ID",
            "SUBMITTED_BY",
            "SUBMITTED_AT",
            "LOCATION_COORDS",
            "MAPS_LINK",
            "PHOTO_URL",
            "OWNER_NAME",
            "OWNER_PHONE",
            "OWNER_EMAIL",
            "CITY_STATE",
            "SOURCE_PLATFORM",
            "SOURCE_LINK",
            "ADMIN_STATUS",
            "ADMIN_NOTES",
            "DISTANCE_WARNING"
        ])

    rows = ws.get_all_values()

    submission_id = f"SUB-{len(rows):06d}"

    ws.append_row([
        submission_id,
        str(submitted_by),
        now_str(),
        coords,
        maps_link,
        photo_url,
        owner_name,
        owner_phone,
        owner_email,
        city_state,
        source_platform,
        source_link,
        "PENDING",
        "",
        distance_warning
    ])

    return submission_id

def create_owner_direct(
        created_by,
        coords,
        maps_link,
        photo_url,
        owner_name,
        owner_phone,
        owner_email,
        city_state,
        source_platform,
        source_link):

    owners = owners_ws()

    owner_id = next_owner_id()

    owners.append_row([
        owner_id,
        "Truck Owner",
        owner_name,
        owner_phone,
        owner_email,
        city_state,
        source_platform,
        source_link,
        maps_link,
        photo_url,
        created_by,
        "APPROVED",
        created_by,
        now_str(),
        "",
        "",
        coords
    ])

    return owner_id

def approve_owner(owner_id: str, approved_by: str):
    ws = owners_ws()
    rows = ws.get_all_values()
    for i, r in enumerate(rows[1:], start=2):
        if r and r[0] == owner_id:
            ws.update_cell(i, 12, "APPROVED")  # OWNER_STATUS
            ws.update_cell(i, 13, str(approved_by))
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

def approve_owner_submission(submission_id):

    ss = _client().open_by_key(SPREADSHEET_ID)
    ws = ss.worksheet("OWNER_SUBMISSIONS")

    rows = ws.get_all_values()

    for i, r in enumerate(rows[1:], start=2):

        if r[0] == submission_id:

            # ===== SAFETY LOCK =====
            status = r[12]

            if status != "PENDING":
                return None

            # mark processing immediately
            ws.update_cell(i, 13, "PROCESSING")

            owner_id = next_owner_id()

            owners = owners_ws()

            # r[5] contains the TELEGRAM photo file_id
            owners.append_row([
                owner_id,
                "Truck Owner",
                r[6],
                r[7],
                r[8],
                r[9],
                r[10],
                r[11],
                r[4],
                r[5],   # store TELEGRAM file_id (used later to resend photo)
                r[1],
                "APPROVED",
                "",
                now_str(),
                "",
                "",
                r[3]
            ])

            # finalize status
            ws.update_cell(i, 13, "APPROVED")

            return owner_id

def get_pending_owner_submissions():

    ss = _client().open_by_key(SPREADSHEET_ID)
    ws = ss.worksheet("OWNER_SUBMISSIONS")

    rows = ws.get_all_values()[1:]

    pending = []

    for r in rows:
        if len(r) > 12 and r[12] == "PENDING":
            pending.append(r)

    return pending