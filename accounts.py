from users import assign_role, register_user_pending, ensure_admin, get_user_status_role
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram import InputMediaPhoto
from telegram.ext import (
    ContextTypes,
    filters
)

from sheets_logger import (
    create_owner_submission,
    check_nearby_accounts,
    approve_owner_submission,
    reject_owner_submission,
    get_pending_owner_submissions,
    create_owner_direct
)
from config import ADMIN_IDS
from menus import (
    open_menu_for_role,
    accounts_menu,
    PANEL_ITEMS, PANEL_ACCOUNTS, PANEL_WORKFLOW, PANEL_USERS,
    PANEL_TASKS, PANEL_REPORTS, PANEL_SYSTEM, PANEL_BACK,
    BTN_PENDING_ACCOUNTS
)

from items import handle_items_panel

def log_line(label, value=""):
    print(f"[BOT DEBUG] {label}: {value}")

def log_block(title):
    print(f"\n========== {title} ==========")

async def debug_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_block("UPDATE RECEIVED")
    print(update)

ENABLE_SHEETS = True  # Set to True when going live
ROLE_CACHE = {}
ADMIN_CACHE = set()

POSTPONED_OWNER_SUBMISSIONS = {}
SECOND_BOT_WARNING_SHOWN = False

# simple rate limiter (per user)
USER_RATE_LIMIT = {}
RATE_LIMIT_SECONDS = 0.4

async def get_cached_role(context, user_id):
    if user_id in ROLE_CACHE:
        return ROLE_CACHE[user_id]

    role, status = await run_sheet(context, get_user_status_role, user_id)
    ROLE_CACHE[user_id] = (role, status)
    return role, status

# ================= ACCOUNT CREATION SESSION =================
ACCOUNT_NONE = 0
ACCOUNT_TYPE = 1
ACCOUNT_OWNER_NAME = 2
ACCOUNT_OWNER_PHONE = 3
ACCOUNT_OWNER_EMAIL = 4
ACCOUNT_OWNER_SOCIALS = 5
ACCOUNT_OWNER_CITY = 6
ACCOUNT_OWNER_STATE = 7
ACCOUNT_CONFIRM = 8
ACCOUNT_LOCATION = 13
ACCOUNT_PHOTO = 14
ACCOUNT_EDIT_SELECT = 20
ACCOUNT_EDIT_NAME = 9
ACCOUNT_EDIT_PHONE = 10
ACCOUNT_EDIT_CITY = 11
ACCOUNT_EDIT_STATE = 12
ACCOUNT_BUSY = 99

# ================= STATE SELECTOR =================

STATE_LIST = [

    # ---- MEXICO (priority trucking states first) ----
    "CHIHUAHUA",
    "NUEVO LEON",
    "COAHUILA",
    "TAMAULIPAS",
    "SONORA",
    "BAJA CALIFORNIA",
    "JALISCO",
    "GUANAJUATO",
    "QUERETARO",
    "SAN LUIS POTOSI",
    "MEXICO",
    "CDMX",
    "AGUASCALIENTES",
    "ZACATECAS",
    "DURANGO",
    "MICHOACAN",
    "PUEBLA",
    "VERACRUZ",
    "YUCATAN",
    "QUINTANA ROO",

    # ---- USA (auction + trucking heavy states first) ----
    "TEXAS",
    "CALIFORNIA",
    "ARIZONA",
    "NEW MEXICO",
    "OKLAHOMA",
    "KANSAS",
    "MISSOURI",
    "ARKANSAS",
    "LOUISIANA",
    "ILLINOIS",
    "INDIANA",
    "OHIO",
    "GEORGIA",
    "FLORIDA",
    "TENNESSEE",
    "KENTUCKY",
    "COLORADO",
    "UTAH",
    "NEVADA",
    "WASHINGTON",
    "OREGON",
    "PENNSYLVANIA",
    "NEW YORK"
]


def state_keyboard(page="MEXICO", filter_text=None):

    if page == "MEXICO":
        states = STATE_LIST[:20]
    else:
        states = STATE_LIST[20:]

    if filter_text:
        states = [s for s in STATE_LIST if s.startswith(filter_text)]

    rows = []
    row = []

    for s in states:
        row.append(KeyboardButton(s))

        if len(row) == 3:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([
        KeyboardButton("🇲🇽 MEXICO"),
        KeyboardButton("🇺🇸 USA")
    ])

    rows.append([KeyboardButton("🔙 BACK")])

    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def base_nav_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🏠 MENU")]],
        resize_keyboard=True
    )

def lock_user(context):
    context.user_data["account_state"] = ACCOUNT_BUSY

def unlock_user(context, state):
    context.user_data["account_state"] = state

def edit_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Name")],
            [KeyboardButton("Phone")],
            [KeyboardButton("City")],
            [KeyboardButton("State")],
            [KeyboardButton("Location")],
            [KeyboardButton("🔙 BACK")]
        ],
        resize_keyboard=True
    )

def confirm_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("✅ CONFIRM")],
            [KeyboardButton("✏ EDIT")],
            [KeyboardButton("❌ CANCEL")]
        ],
        resize_keyboard=True
    )

def clear_user_session(context):
    context.user_data.clear()

import asyncio

async def run_sheet(context, func, *args, **kwargs):

    loop = asyncio.get_running_loop()

    try:
        return await loop.run_in_executor(
            None,
            lambda: func(*args, **kwargs)
        )

    except Exception as e:
        print("SHEETS ERROR:", repr(e))
        return None

# =========================================================
# START BUTTON PRESSED
# =========================================================
async def start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    uid = str(user.id)
    context.user_data["entered"] = True
    context.user_data["menu_loaded"] = False

    # ---------- ADMIN ----------
    if uid in ADMIN_CACHE:
        ROLE_CACHE[uid] = ("ADMIN", "ACTIVE")
        context.user_data["cached_role"] = "ADMIN"
        await open_menu_for_role(update, context, "ADMIN")
        return

    is_admin = await run_sheet(context, ensure_admin, uid, user.username or "", user.full_name)
    if is_admin:
        ADMIN_CACHE.add(uid)
        ROLE_CACHE[uid] = ("ADMIN", "ACTIVE")
        context.user_data["cached_role"] = "ADMIN"
        await open_menu_for_role(update, context, "ADMIN")
        return

    # ---------- CHECK USER STATUS ----------
    role, status = await get_cached_role(context, uid)

    # ACTIVE USER → MENU
    if status == "ACTIVE":
        context.user_data["cached_role"] = role
        await open_menu_for_role(update, context, role)
        return

    # PENDING USER
    if status == "PENDING":
        await update.message.reply_text("⏳ Waiting for administrator approval.")
        return

    # ---------- BRAND NEW USER ----------
    if ENABLE_SHEETS:
        await run_sheet(
            context,
            register_user_pending,
            telegram_id=uid,
            username=user.username or "",
            full_name=user.full_name
        )

        from users import notify_admin_new_user
        await notify_admin_new_user(context, uid, user.username or "", user.full_name)
    else:
        print("TEST MODE — USER WOULD BE REGISTERED:", uid)

    ROLE_CACHE[uid] = ("REGISTERING", "REGISTERING")

    # Always rebuild wizard fresh
    clear_user_session(context)
    context.user_data["account_state"] = ACCOUNT_LOCATION
    context.user_data["account_draft"] = {"type": "WORKER"}
    context.user_data["cached_role"] = "REGISTERING"

    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("📍 SEND LOCATION", request_location=True)],
            [KeyboardButton("🔙 CANCEL")]
        ],
        resize_keyboard=True
    )

    await update.message.reply_text(
        "Welcome 👋\nFirst send the yard location:",
        reply_markup=keyboard
    )
    return

async def owner_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split("|")

    if len(parts) < 3:
        return

    action = parts[0]
    submission_id = parts[1]
    worker_id = parts[2]

    admin_id = str(query.from_user.id)

    if str(admin_id) not in [str(a) for a in ADMIN_IDS]:
        await query.answer("⛔ Admin only", show_alert=True)
        return

    if action == "OWNER_APPROVE":

        try:
            if ENABLE_SHEETS:

                rows = await run_sheet(context, get_pending_owner_submissions)

                submission_found = False

                for r in rows:
                    if r[0] == submission_id:
                        worker_id = r[1]
                        submission_found = True
                        break

                # submission already processed by another admin
                if not submission_found:
                    await query.edit_message_text(
                        f"⚠️ Submission {submission_id} already processed."
                    )
                    return

                owner_id = await run_sheet(
                    context,
                    approve_owner_submission,
                    submission_id
                )

                if not owner_id:
                    await query.edit_message_text(
                        f"⚠️ Submission {submission_id} already processed."
                    )
                    return

        except Exception as e:
            log_block("OWNER APPROVE ERROR")
            log_line("ERROR", repr(e))

        data = POSTPONED_OWNER_SUBMISSIONS.pop(submission_id, None)

        if data and isinstance(data, dict):

            try:

                if "media_msgs" in data:
                    for mid in data["media_msgs"]:
                        try:
                            await context.bot.delete_message(
                                chat_id=query.message.chat.id,
                                message_id=mid
                            )
                        except:
                            pass

                if "main_msg" in data:
                    await context.bot.delete_message(
                        chat_id=query.message.chat.id,
                        message_id=data["main_msg"]
                    )

            except Exception as e:
                log_line("DELETE_MAIN_MSG_ERROR", repr(e))

        try:
            await query.delete_message()
        except:
            pass

        POSTPONED_OWNER_SUBMISSIONS[submission_id] = "REVIEWED"

        # notify worker who submitted
        try:
            if worker_id:
                await context.bot.send_message(
                    chat_id=worker_id,
                    text=f"✅ Your submitted yard has been approved.\nOwner ID: {owner_id}"
                )
        except Exception as e:
            log_block("WORKER APPROVAL NOTIFY ERROR")
            log_line("ERROR", repr(e))

    elif action == "OWNER_REJECT":

        try:
            if ENABLE_SHEETS:

                log_block("OWNER REJECT START")
                log_line("SUBMISSION_ID", submission_id)

                result = await run_sheet(
                    context,
                    reject_owner_submission,
                    submission_id
                )

                log_line("REJECT_RESULT", result)

        except Exception as e:
            log_block("OWNER REJECT ERROR")
            log_line("ERROR", repr(e))

        data = POSTPONED_OWNER_SUBMISSIONS.pop(submission_id, None)

        if data and isinstance(data, dict):

            try:

                if "media_msgs" in data:
                    for mid in data["media_msgs"]:
                        try:
                            await context.bot.delete_message(
                                chat_id=query.message.chat.id,
                                message_id=mid
                            )
                        except:
                            pass

                if "main_msg" in data:
                    await context.bot.delete_message(
                        chat_id=query.message.chat.id,
                        message_id=data["main_msg"]
                    )

            except Exception as e:
                log_line("DELETE_MAIN_MSG_ERROR", repr(e))

        try:
            await query.delete_message()
        except:
            pass

        POSTPONED_OWNER_SUBMISSIONS[submission_id] = "REVIEWED"

        # notify worker
        try:
            if worker_id:
                await context.bot.send_message(
                    chat_id=worker_id,
                    text="❌ Your submitted yard was rejected by admin."
                )
        except Exception as e:
            log_block("WORKER REJECT NOTIFY ERROR")
            log_line("ERROR", repr(e))

    elif action == "OWNER_POSTPONE":

        POSTPONED_OWNER_SUBMISSIONS[submission_id] = {
            "message": query.message.text,
            "photo": query.message.photo[-1].file_id if (query.message.photo and len(query.message.photo) > 0) else None
        }

        await query.edit_message_reply_markup(reply_markup=None)

        await query.message.reply_text(
            f"⏳ Submission {submission_id} postponed.\nYou can review it later in WORKFLOW."
        )
