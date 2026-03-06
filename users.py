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

# ================================
# OWNERS TABLE
# ================================
TAB_OWNERS = "OWNERS_MASTER"

def owners_sheet():
    return _worksheet(TAB_OWNERS, [
        "OWNER_ID",
        "OWNER_TYPE",
        "OWNER_NAME",
        "OWNER_PHONE",
        "OWNER_EMAIL",
        "CITY_STATE",
        "SOURCE_PLATFORM",
        "SOURCE_LINK",
        "MAPS_LINK",
        "LOCATION_PHOTO_URL",
        "CLAIMED_BY_FINDER_ID",
        "OWNER_STATUS",
        "APPROVED_BY",
        "CREATED_AT",
        "LAST_CONTACTED_AT",
        "NOTES",
        "LOCATION_COORDS"
    ])


# ================================
# OWNER ID GENERATOR
# ================================
def _next_owner_id():

    sh = owners_sheet()
    rows = sh.get_all_values()

    if len(rows) <= 1:
        return "OWN0001"

    last = rows[-1][0]

    try:
        num = int(last.replace("OWN", ""))
        num += 1
    except:
        num = len(rows)

    return f"OWN{num:04d}"

# ================================
# LOCATION DISTANCE (METERS)
# ================================
import math

def _distance_meters(lat1, lon1, lat2, lon2):

    R = 6371000  # Earth radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return R * c

# ================================
# LOCATION CACHE (FAST SEARCH)
# ================================
_OWNER_LOCATION_CACHE = None

def _load_owner_locations():

    global _OWNER_LOCATION_CACHE

    if _OWNER_LOCATION_CACHE is not None:
        return _OWNER_LOCATION_CACHE

    sh = owners_sheet()
    rows = sh.get_all_values()[1:]

    cache = []

    for r in rows:

        try:
            link = r[8]
            coord = link.split("?q=")[1]
            lat, lon = map(float, coord.split(","))

            cache.append({
                "lat": lat,
                "lon": lon
            })

        except:
            pass

    _OWNER_LOCATION_CACHE = cache

    return cache

# ================================
# CREATE OWNER
# ================================
def create_owner(owner_type, name, phone, state, city, address, maps_link, photo_file_id, created_by):

    sh = owners_sheet()
    rows = sh.get_all_values()
    locations = _load_owner_locations()
    owner_id = _next_owner_id()

    # extract new coordinates
    try:
        coord = maps_link.split("?q=")[1]
        new_lat, new_lon = map(float, coord.split(","))
    except Exception:
        new_lat, new_lon = None, None

    for r, loc in zip(rows[1:], locations):

        # duplicate phone check
        if len(r) > 3 and r[3] == str(phone):
            return {
                "status": "DUPLICATE_PHONE",
            }

        # duplicate location check
        try:
            lat = loc["lat"]
            lon = loc["lon"]

            if new_lat is not None:

                distance = _distance_meters(new_lat, new_lon, lat, lon)

                if distance <= 100:
                    return {
                        "status": "DUPLICATE_LOCATION",
                        "distance_m": int(distance)
                    }

        except Exception:
            pass

    # store pending for admin approval
    sh.append_row([
        owner_id,                         # OWNER_ID
        safe_text(owner_type),            # OWNER_TYPE
        safe_text(name),                  # OWNER_NAME
        safe_text(phone),                 # OWNER_PHONE
        "",                               # OWNER_EMAIL
        f"{safe_text(city)}, {safe_text(state)}",  # CITY_STATE
        "telegram_bot",                   # SOURCE_PLATFORM
        "",                               # SOURCE_LINK
        safe_text(maps_link),             # MAPS_LINK
        safe_text(photo_file_id or ""),   # LOCATION_PHOTO_URL
        "",                               # CLAIMED_BY_FINDER_ID
        "PENDING",                        # OWNER_STATUS
        "",                               # APPROVED_BY
        now_str(),                        # CREATED_AT
        "",                               # LAST_CONTACTED_AT
        "",                               # NOTES
        f"{new_lat},{new_lon}" if new_lat else ""  # LOCATION_COORDS
    ])

    # refresh location cache
    global _OWNER_LOCATION_CACHE
    _OWNER_LOCATION_CACHE = None

    return {
        "status": "CREATED_PENDING"
    }