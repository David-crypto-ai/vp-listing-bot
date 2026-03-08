import os
from telegram.ext import CallbackQueryHandler
from users import assign_role, register_user_pending, ensure_admin, get_user_status_role
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
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

def log_line(label, value=""):
    print(f"[BOT DEBUG] {label}: {value}")

def log_block(title):
    print(f"\n========== {title} ==========")

async def debug_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_block("UPDATE RECEIVED")
    print(update)

TOKEN = os.environ["TELEGRAM_TOKEN"]

ENABLE_SHEETS = True  # Set to True when going live
ROLE_CACHE = {}
ADMIN_CACHE = set()

POSTPONED_OWNER_SUBMISSIONS = {}

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
ACCOUNT_LOCATION = 15
ACCOUNT_PHOTO = 13
ACCOUNT_DUPLICATE_CHECK = 14
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
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

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

async def route_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    # capture message text safely (buttons, captions, etc)
    text = (update.message.text or "").strip().upper()
    if not text and update.message.caption:
        text = update.message.caption.strip()

    uid = str(update.effective_user.id)
    user = update.effective_user

    # session warm-start after approval (VERY IMPORTANT FIRST)
    forced = context.application.bot_data.get("force_role_cache", {}).pop(str(user.id), None)
    if forced:
        ROLE_CACHE[str(user.id)] = forced

    # allow known approved users even if cache restarted
    role, status = await get_cached_role(context, uid)

    # ===== AUTO SESSION RECOVERY (CRITICAL) =====
    state = context.user_data.get("account_state", ACCOUNT_NONE)

    # ACTIVE USERS → reopen menu only if user typed random text
    if status == "ACTIVE" and state == ACCOUNT_NONE and not context.user_data.get("account_draft"):

        # always refresh role menu after updates
        context.user_data["cached_role"] = role

        # if user pressed something unknown or menu button → reload latest menu
        if text not in [
            PANEL_ACCOUNTS,
            PANEL_ITEMS,
            PANEL_WORKFLOW,
            PANEL_USERS,
            PANEL_TASKS,
            PANEL_REPORTS,
            PANEL_SYSTEM,
            PANEL_BACK,
            "➕ ADD ACCOUNT",
            "👤 MY ACCOUNTS",
            "📍 NEARBY ACCOUNTS",
            "🔎 SEARCH ACCOUNT"
        ]:
            await open_menu_for_role(update, context, role)
            return

    # PENDING USERS → always inform
    if status == "PENDING":
        await update.message.reply_text("⏳ Waiting for administrator approval.")
        return

    # REGISTERING USERS (cache lost after restart)
    if status not in ["ACTIVE", "PENDING"] and state == ACCOUNT_NONE:
        context.user_data["account_state"] = ACCOUNT_OWNER_NAME
        context.user_data["account_draft"] = {"type": "WORKER"}
        context.user_data["cached_role"] = "REGISTERING"
        await update.message.reply_text("Let's continue your registration.\nEnter your full name:")
        return
    # ================= ACCOUNT WIZARD HANDLER =================
    state = context.user_data.get("account_state", ACCOUNT_NONE)

    if state != ACCOUNT_NONE:
        # wizard active → use cached role, never query sheets
        role = context.user_data.get("cached_role")
        status = "ACTIVE"

        # fallback only if cache missing (prevents "stuck")
        if not role:
            role, _status = await get_cached_role(context, str(user.id))
            context.user_data["cached_role"] = role
    else:
        context.user_data["cached_role"] = role

        if status != "ACTIVE":
            await update.message.reply_text("⏳ Waiting for administrator approval.")
            return


    # ================= WIZARD STATES =================
    if state != ACCOUNT_NONE:

        if state == ACCOUNT_BUSY:
            return

        # --- SELECT TYPE ---
        if state == ACCOUNT_TYPE:

            if text == "📍 LOCATION":

                context.user_data["account_state"] = ACCOUNT_LOCATION
                context.user_data["account_draft"] = {
                    "type": "OWNER",
                    "distance_warning": ""
                }

                keyboard = ReplyKeyboardMarkup(
                    [
                        [KeyboardButton("📍 SEND LOCATION", request_location=True)],
                        [KeyboardButton("🔙 BACK")]
                    ],
                    resize_keyboard=True
                )

                await update.message.reply_text(
                    "Please send the yard location using the button:",
                    reply_markup=keyboard
                )
                return

            if "ONLINE" in text:
                await update.message.reply_text("Online accounts coming soon")
                return

            if "AUCTION" in text:
                await update.message.reply_text("Auction accounts coming soon")
                return

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_NONE
                await open_menu_for_role(update, context, role)
                return

            return

        # --- OWNER NAME ---
        if state == ACCOUNT_OWNER_NAME:

            if "CONTINUE" in text:
                return

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_TYPE
                await update.message.reply_text(
                    "Select account type:",
                    reply_markup=ReplyKeyboardMarkup(
                        [
                            [KeyboardButton("📍 LOCATION")],
                            [KeyboardButton("🌐 ONLINE")],
                            [KeyboardButton("🏛️ AUCTION")],
                            [KeyboardButton("🔙 BACK")]
                        ],
                        resize_keyboard=True
                    )
                )
                return

            if text in ["➡ CONTINUE", "CONTINUE"]:
                return

            context.user_data.setdefault("account_draft", {})["name"] = text
            context.user_data["account_state"] = ACCOUNT_OWNER_PHONE
            await update.message.reply_text(
                "Enter phone number:",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
            )
            return

        # --- OWNER PHONE ---
        if state == ACCOUNT_OWNER_PHONE:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_NAME
                await update.message.reply_text("Enter owner name:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True))
                return

            context.user_data["account_draft"]["phone"] = text
            context.user_data["account_state"] = ACCOUNT_OWNER_EMAIL

            await update.message.reply_text(
                "Enter email (optional):",
                reply_markup=ReplyKeyboardMarkup(
                    [
                        [KeyboardButton("➡ NEXT")],
                        [KeyboardButton("🔙 BACK")]
                    ],
                    resize_keyboard=True
                )
            )
            return

        if state == ACCOUNT_OWNER_STATE:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_CITY
                await update.message.reply_text(
                    "Enter city:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "🇲🇽 MEXICO":
                await update.message.reply_text(
                    "Select state:",
                    reply_markup=state_keyboard("MEXICO")
                )
                return

            if text == "🇺🇸 USA":
                await update.message.reply_text(
                    "Select state:",
                    reply_markup=state_keyboard("USA")
                )
                return

            matches = [s for s in STATE_LIST if s.startswith(text)]

            if len(matches) > 1:
                await update.message.reply_text(
                    "Select state:",
                    reply_markup=state_keyboard(filter_text=text)
                )
                return

            if text not in STATE_LIST:
                await update.message.reply_text(
                    "Please select a state from the list or type the first letters.",
                    reply_markup=state_keyboard()
                )
                return

            context.user_data["account_draft"]["state"] = text
            context.user_data["account_state"] = ACCOUNT_CONFIRM

            draft = context.user_data["account_draft"]

            await update.message.reply_text(
                f"Review account:\n"
                f"Type: {draft['type']}\n"
                f"Name: {draft['name']}\n"
                f"Phone: {draft['phone']}\n"
                f"City/State: {draft.get('city','') + ', ' if draft.get('city') else ''}{draft.get('state','')}",
                reply_markup=confirm_keyboard()
            )
            return
        
        if state == ACCOUNT_OWNER_EMAIL:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_PHONE
                await update.message.reply_text(
                    "Enter phone number:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "➡ NEXT":
                context.user_data["account_draft"]["email"] = ""
            else:
                context.user_data["account_draft"]["email"] = text

            context.user_data["account_state"] = ACCOUNT_OWNER_SOCIALS

            await update.message.reply_text(
                "Enter social media links (optional):",
                reply_markup=ReplyKeyboardMarkup(
                    [
                        [KeyboardButton("➡ NEXT")],
                        [KeyboardButton("🔙 BACK")]
                    ],
                    resize_keyboard=True
                )
            )
            return
        if state == ACCOUNT_OWNER_SOCIALS:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_EMAIL
                await update.message.reply_text(
                    "Enter email (optional):",
                    reply_markup=ReplyKeyboardMarkup(
                        [
                            [KeyboardButton("➡ NEXT")],
                            [KeyboardButton("🔙 BACK")]
                        ],
                        resize_keyboard=True
                    )
                )
                return

            if text == "➡ NEXT":
                context.user_data["account_draft"]["socials"] = ""
            else:
                context.user_data["account_draft"]["socials"] = text

            context.user_data["account_state"] = ACCOUNT_OWNER_CITY

            await update.message.reply_text(
                "Enter city (optional):",
                reply_markup=ReplyKeyboardMarkup(
                    [
                        [KeyboardButton("➡ NEXT")],
                        [KeyboardButton("🔙 BACK")]
                    ],
                    resize_keyboard=True
                )
            )
            return
            
        # --- OWNER CITY ---
        if state == ACCOUNT_OWNER_CITY:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_PHONE
                await update.message.reply_text(
                    "Enter phone number:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "➡ NEXT":
                context.user_data["account_state"] = ACCOUNT_OWNER_STATE

                await update.message.reply_text(
                    "Select state:",
                    reply_markup=state_keyboard()
                )
                return

            context.user_data["account_draft"]["city"] = text
            context.user_data["account_state"] = ACCOUNT_OWNER_STATE

            await update.message.reply_text(
                "Select state:",
                reply_markup=state_keyboard()
            )
            return

        # --- CONFIRMATION STEP ---
        if state == ACCOUNT_CONFIRM:

            if "CANCEL" in text:
                clear_user_session(context)
                await open_menu_for_role(update, context, role)
                return

            if "EDIT" in text:
                context.user_data["account_state"] = ACCOUNT_EDIT_SELECT
                await update.message.reply_text(
                    "Select field to edit:",
                    reply_markup=edit_menu_keyboard()
                )
                return

            if "CONFIRM" in text:

                draft = context.user_data["account_draft"]

                # Step 1: Ensure photo exists
                if not draft.get("photo_file_id"):

                    context.user_data["account_state"] = ACCOUNT_PHOTO

                    await update.message.reply_text(
                        "📸 Now send a yard photo:",
                        reply_markup=ReplyKeyboardMarkup(
                            [[KeyboardButton("🔙 BACK")]],
                            resize_keyboard=True
                        )
                    )
                    return

                # Step 3: Everything collected → SAVE
                lock_user(context)
                save_success = False

                log_block("OWNER SAVE DEBUG")
                log_line("TYPE", draft.get("type"))
                log_line("NAME", draft.get("name"))
                log_line("PHONE", draft.get("phone"))
                log_line("CITY", draft.get("city"))
                log_line("STATE", draft.get("state"))
                log_line("MAPS_LINK", draft.get("maps_link"))
                log_line("PHOTO_FILE_ID", draft.get("photo_file_id"))
                log_line("UID", uid)

                try:
                    if ENABLE_SHEETS:

                        # ADMIN → write directly to OWNERS_MASTER
                        if uid in ADMIN_IDS:

                            owner_id = await run_sheet(
                                context,
                                create_owner_direct,
                                uid,
                                draft.get("coords",""),
                                draft.get("maps_link",""),
                                draft.get("photo_file_id",""),
                                draft.get("name",""),
                                draft.get("phone",""),
                                draft.get("email",""),
                                draft.get("socials",""),
                                f"{draft.get('city','')}, {draft.get('state','')}".strip(", "),
                                draft.get("source_platform",""),
                                draft.get("source_link","")
                            )

                            submission_id = None

                        # WORKER → send to submission queue
                        else:

                            submission_id = await run_sheet(
                                context,
                                create_owner_submission,
                                uid,
                                draft.get("coords",""),
                                draft.get("maps_link",""),
                                draft.get("photo_file_id",""),
                                draft.get("name",""),
                                draft.get("phone",""),
                                draft.get("email",""),
                                draft.get("socials",""),
                                f"{draft.get('city','')}, {draft.get('state','')}".strip(", "),
                                draft.get("source_platform",""),
                                draft.get("source_link",""),
                                draft.get("distance_warning","")
                            )
                    else:
                        print("TEST MODE — OWNER WOULD BE SAVED:", draft)

                    save_success = True

                except Exception as e:
                    log_block("OWNER SAVE ERROR")
                    log_line("ERROR", repr(e))
                    log_line("DRAFT DATA", draft)
                    unlock_user(context, ACCOUNT_CONFIRM)

                if save_success:

                    # ===== PUSH SUBMISSION TO ADMINS =====
                    try:

                        caption = (
                            "🚨 NEW ACCOUNT SUBMISSION\n\n"
                            f"Submission ID: {submission_id}\n"
                            f"Name: {draft.get('name','')}\n"
                            f"Phone: {draft.get('phone','')}\n"
                            f"City: {draft.get('city','')}\n"
                            f"State: {draft.get('state','')}\n"
                            f"Finder ID: {uid}"
                        )

                        if submission_id and ADMIN_IDS:

                            for admin in ADMIN_IDS:

                                keyboard = InlineKeyboardMarkup([
                                    [
                                        InlineKeyboardButton(
                                            "✅ APPROVE",
                                            callback_data=f"OWNER_APPROVE|{submission_id}|{uid}"
                                        ),
                                        InlineKeyboardButton(
                                            "❌ REJECT",
                                            callback_data=f"OWNER_REJECT|{submission_id}|{uid}"
                                        )
                                    ]
                                ])

                                if draft.get("photo_file_id"):

                                    await context.bot.send_photo(
                                        chat_id=admin,
                                        photo=draft["photo_file_id"],
                                        caption=caption,
                                        reply_markup=keyboard
                                    )

                                else:

                                    await context.bot.send_message(
                                        chat_id=admin,
                                        text=caption,
                                        reply_markup=keyboard
                                    )

                    except Exception as e:
                        log_block("ADMIN PUSH ERROR")
                        log_line("ERROR", repr(e))

                    if uid in ADMIN_IDS:
                        message = "✅ Account created successfully."
                    else:
                        message = "⏳ Account submitted. Waiting for admin approval."

                    await update.message.reply_text(
                        message,
                        reply_markup=base_nav_keyboard()
                    )

                    clear_user_session(context)
                    await open_menu_for_role(update, context, role)
                    return
                else:
                    await update.message.reply_text(
                        "❌ Error saving account. Please try again.",
                        reply_markup=confirm_keyboard()
                    )
                    return

        # ================= EDIT SELECT =================
        if state == ACCOUNT_EDIT_SELECT:

            if text == "Name":
                context.user_data["account_state"] = ACCOUNT_EDIT_NAME
                await update.message.reply_text(
                    "Enter new name:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "Phone":
                context.user_data["account_state"] = ACCOUNT_EDIT_PHONE
                await update.message.reply_text(
                    "Enter new phone:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "City":
                context.user_data["account_state"] = ACCOUNT_EDIT_CITY
                await update.message.reply_text(
                    "Enter new city:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "State":
                context.user_data["account_state"] = ACCOUNT_EDIT_STATE
                await update.message.reply_text(
                    "Enter new state:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "Location":
                context.user_data["account_state"] = ACCOUNT_LOCATION
                keyboard = ReplyKeyboardMarkup(
                    [[KeyboardButton("📍 SEND LOCATION", request_location=True)],
                     [KeyboardButton("🔙 BACK")]],
                    resize_keyboard=True
                )
                await update.message.reply_text("Send new location:", reply_markup=keyboard)
                return

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_CONFIRM
                draft = context.user_data["account_draft"]

                await update.message.reply_text(
                    f"Review account:\n"
                    f"Type: {draft['type']}\n"
                    f"Name: {draft['name']}\n"
                    f"Phone: {draft['phone']}\n"
                    f"City/State: {draft.get('city','') + ', ' if draft.get('city') else ''}{draft.get('state','')}",
                    reply_markup=confirm_keyboard()
                )
                return

            return


        # ================= APPLY EDIT =================
        if state in [ACCOUNT_EDIT_NAME, ACCOUNT_EDIT_PHONE, ACCOUNT_EDIT_CITY, ACCOUNT_EDIT_STATE]:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_EDIT_SELECT
                await update.message.reply_text(
                    "Select field to edit:",
                    reply_markup=edit_menu_keyboard()
                )
                return

            if state == ACCOUNT_EDIT_NAME:
                context.user_data.setdefault("account_draft", {})["name"] = text

            elif state == ACCOUNT_EDIT_PHONE:
                context.user_data["account_draft"]["phone"] = text

            elif state == ACCOUNT_EDIT_CITY:
                context.user_data["account_draft"]["city"] = text

            elif state == ACCOUNT_EDIT_STATE:
                context.user_data["account_draft"]["state"] = text

            context.user_data["account_state"] = ACCOUNT_CONFIRM
            draft = context.user_data["account_draft"]

            await update.message.reply_text(
                f"Review account:\n"
                f"Type: {draft['type']}\n"
                f"Name: {draft['name']}\n"
                f"Phone: {draft['phone']}\n"
                f"City/State: {draft.get('city','') + ', ' if draft.get('city') else ''}{draft.get('state','')}",
                reply_markup=confirm_keyboard()
            )
            return

        # ================= LOCATION CAPTURE =================
        if state == ACCOUNT_LOCATION:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_CONFIRM
                await update.message.reply_text(
                    "Back to review:",
                    reply_markup=confirm_keyboard()
                )
                return

            if update.message.location:
                loc = update.message.location
                draft = context.user_data.setdefault("account_draft", {})

                maps_link = f"https://maps.google.com/?q={loc.latitude},{loc.longitude}"

                log_block("LOCATION RECEIVED")
                log_line("LAT", loc.latitude)
                log_line("LON", loc.longitude)
                log_line("MAPS_LINK", maps_link)

                draft["maps_link"] = maps_link
                draft["coords"] = f"{loc.latitude},{loc.longitude}"
                draft["lat"] = loc.latitude
                draft["lon"] = loc.longitude

                # ===== CHECK FOR NEARBY YARDS =====
                try:

                    # prevent duplicate check from running twice
                    if draft.get("duplicate_checked"):
                        nearby = []
                    else:
                        nearby = await run_sheet(
                            context,
                            check_nearby_accounts,
                            loc.latitude,
                            loc.longitude
                        )
                        draft["duplicate_checked"] = True

                    log_block("NEARBY SEARCH RESULT")
                    log_line("NEARBY_ROWS", nearby)

                    if nearby:
                        nearest = nearby[0]
                        owner_row, dist = nearest

                        warning = f"WITHIN_{int(dist)}M_OF_{owner_row[0]}"
                        draft["distance_warning"] = warning

                        log_block("NEARBY OWNER DETECTED")
                        log_line("DISTANCE_METERS", int(dist))
                        log_line("OWNER_ID", owner_row[0])

                        draft["duplicate_message"] = (
                            f"⚠ Possible duplicate yard\n"
                            f"Distance: {int(dist)} meters\n"
                            f"Owner ID: {owner_row[0]}"
                        )

                        try:
                            log_block("DUPLICATE PHOTO DEBUG")
                            log_line("OWNER_ROW", owner_row)
                            log_line("ROW_LENGTH", len(owner_row))

                            existing_photo = None

                            if len(owner_row) >= 10:
                                existing_photo = owner_row[9]

                            log_line("EXISTING_PHOTO_CELL", existing_photo)

                            await update.message.reply_text(
                                "⚠ Possible duplicate yard detected.\n"
                                f"Distance: {int(dist)} meters\n"
                                f"Owner ID: {owner_row[0]}"
                            )

                            if existing_photo:

                                draft["existing_photo"] = existing_photo

                                await update.message.reply_photo(
                                    photo=existing_photo,
                                    caption="Existing yard photo for comparison"
                                )

                            else:
                                await update.message.reply_text(
                                    "⚠ Existing yard photo not found."
                                )

                            context.user_data["account_state"] = ACCOUNT_DUPLICATE_CHECK

                            await update.message.reply_text(
                                "Compare the location in front of you with the saved yard photo.\n\nContinue anyway?",
                                reply_markup=ReplyKeyboardMarkup(
                                    [
                                        [KeyboardButton("➡ CONTINUE")],
                                        [KeyboardButton("❌ CANCEL")]
                                    ],
                                    resize_keyboard=True
                                )
                            )
                            return

                        except Exception as e:
                            log_block("EXISTING PHOTO ERROR")
                            log_line("ERROR", repr(e))
                except Exception as e:
                    log_block("DISTANCE CHECK ERROR")
                    log_line("ERROR", repr(e))

                context.user_data["account_state"] = ACCOUNT_PHOTO

                if not draft.get("photo_prompt_sent"):

                    draft["photo_prompt_sent"] = True

                    await update.message.reply_text(
                        "📸 Now send a yard photo:",
                        reply_markup=ReplyKeyboardMarkup(
                            [[KeyboardButton("🔙 BACK")]],
                            resize_keyboard=True
                        )
                    )
                return

            else:
                await update.message.reply_text(
                    "Please send the location using the button."
                )
                return

        # ================= PHOTO CAPTURE =================
        if state == ACCOUNT_PHOTO:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_LOCATION
                keyboard = ReplyKeyboardMarkup(
                    [[KeyboardButton("📍 SEND LOCATION", request_location=True)],
                     [KeyboardButton("🔙 BACK")]],
                    resize_keyboard=True
                )
                await update.message.reply_text(
                    "Send location again:",
                    reply_markup=keyboard
                )
                return

            if update.message.photo:
                draft = context.user_data.setdefault("account_draft", {})

                photo = update.message.photo[-1]
                draft["photo_file_id"] = photo.file_id

                log_block("PHOTO RECEIVED")
                log_line("FILE_ID", photo.file_id)

                file = await context.bot.get_file(photo.file_id)
                draft["photo_url"] = file.file_path

                log_line("FILE_PATH", draft["photo_url"])

                if draft.get("duplicate_confirmed"):

                    if not draft.get("name"):
                        context.user_data["account_state"] = ACCOUNT_OWNER_NAME

                        await update.message.reply_text(
                            "Enter owner name:",
                            reply_markup=ReplyKeyboardMarkup(
                                [[KeyboardButton("🔙 BACK")]],
                                resize_keyboard=True
                            )
                        )
                    else:
                        context.user_data["account_state"] = ACCOUNT_CONFIRM

                        draft = context.user_data["account_draft"]

                        await update.message.reply_text(
                            f"Review account:\n"
                            f"Type: {draft['type']}\n"
                            f"Name: {draft['name']}\n"
                            f"Phone: {draft['phone']}\n"
                            f"City/State: {draft.get('city','') + ', ' if draft.get('city') else ''}{draft.get('state','')}",
                            reply_markup=confirm_keyboard()
                        )
                    return

                if draft.get("distance_warning"):
                    context.user_data["account_state"] = ACCOUNT_DUPLICATE_CHECK
                else:
                    context.user_data["account_state"] = ACCOUNT_OWNER_NAME

                if draft.get("distance_warning"):

                    keyboard = ReplyKeyboardMarkup(
                        [
                            [KeyboardButton("➡ CONTINUE")],
                            [KeyboardButton("❌ CANCEL")]
                        ],
                        resize_keyboard=True
                    )

                    message = "Location captured ✅\nPhoto captured ✅\n\n"

                    if draft.get("duplicate_message"):
                        message += draft["duplicate_message"] + "\n\nContinue anyway?"
                    else:
                        message += "Continue to owner details?"

                    await update.message.reply_text(
                        message,
                        reply_markup=keyboard
                    )

                else:

                    keyboard = ReplyKeyboardMarkup(
                        [
                            [KeyboardButton("➡ CONTINUE")],
                            [KeyboardButton("❌ CANCEL")]
                        ],
                        resize_keyboard=True
                    )

                    await update.message.reply_text(
                        "Location and photo captured.\n\n"
                        "Continue to owner details?",
                        reply_markup=keyboard
                    )

                return

            return

        # ================= DUPLICATE CHECK =================
        if state == ACCOUNT_DUPLICATE_CHECK:

            if "CANCEL" in text:
                clear_user_session(context)
                await open_menu_for_role(update, context, role)
                return

            if "CONTINUE" in text:

                draft = context.user_data.setdefault("account_draft", {})
                draft["duplicate_confirmed"] = True

                # if photo not yet sent → ask for photo
                if not draft.get("photo_file_id"):

                    context.user_data["account_state"] = ACCOUNT_PHOTO

                    await update.message.reply_text(
                        "📸 Now send a yard photo:",
                        reply_markup=ReplyKeyboardMarkup(
                            [[KeyboardButton("🔙 BACK")]],
                            resize_keyboard=True
                        )
                    )
                    return

                # photo already exists → move forward
                context.user_data["account_state"] = ACCOUNT_OWNER_NAME

                await update.message.reply_text(
                    "Enter owner name:",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("🔙 BACK")]],
                        resize_keyboard=True
                    )
                )
                return

            return

    # ================= ACCOUNTS (ADMIN + WORKERS) =================
    if text == PANEL_ACCOUNTS and status == "ACTIVE":

        await update.message.reply_text(
            "Accounts Menu",
            reply_markup=accounts_menu()
        )
        return

    # ================= ADD ACCOUNT =================
    if text == "➕ ADD ACCOUNT" and status == "ACTIVE":

        context.user_data["account_state"] = ACCOUNT_TYPE
        context.user_data["account_draft"] = {
            "email": "",
            "city": "",
            "state": "",
            "source_platform": "",
            "source_link": "",
            "distance_warning": "",
            "coords": "",
            "maps_link": "",
            "photo_url": ""
        }

        keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("📍 LOCATION")],
                [KeyboardButton("🌐 ONLINE")],
                [KeyboardButton("🏛️ AUCTION")],
                [KeyboardButton("🔙 BACK")]
            ],
            resize_keyboard=True
        )

        await update.message.reply_text(
            "Select account type:",
            reply_markup=keyboard,
        )
        return

    # ================= MY ACCOUNTS =================
    if text == "👤 MY ACCOUNTS" and status == "ACTIVE":

        await update.message.reply_text(
            "📋 Your accounts will appear here (Google Sheets integration coming next)."
        )
        return


    # ================= NEARBY ACCOUNTS =================
    if text == "📍 NEARBY ACCOUNTS" and status == "ACTIVE":

        await update.message.reply_text(
            "📍 Nearby accounts feature coming soon."
        )
        return


    # ================= SEARCH ACCOUNT =================
    if text == "🔎 SEARCH ACCOUNT" and status == "ACTIVE":

        await update.message.reply_text(
            "🔎 Send a name or phone number to search accounts (feature coming next)."
        )
        return
        
    # ================= ADMIN PANEL NAVIGATION =================
    if role == "ADMIN":
        if BTN_PENDING_ACCOUNTS in text:

            try:
                rows = await run_sheet(
                    context,
                    get_pending_owner_submissions
                )

                if not rows:
                    await update.message.reply_text("No pending owner submissions.")
                    return

                await update.message.reply_text("📋 Pending Account Submissions")

                for r in rows:

                    submission_id = r[0]
                    worker_id = r[1]

                    coords = r[3]
                    maps_link = r[4]
                    photo = r[5]

                    name = r[6]
                    phone = r[7]
                    email = r[8]
                    socials = r[9]
                    city = r[10]

                    caption = (
                        "🚨 NEW YARD SUBMISSION\n\n"
                        f"Submission ID: {submission_id}\n"
                        f"👤 Name: {name}\n"
                        f"📞 Phone: {phone}\n"
                        f"📧 Email: {email}\n"
                        f"🌐 Socials: {socials}\n"
                        f"📍 City: {city}\n"
                        f"🗺 Maps: {maps_link}\n"
                        f"🆔 Finder ID: {worker_id}"
                    )

                    keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ APPROVE", callback_data=f"OWNER_APPROVE|{submission_id}|{worker_id}"),
                            InlineKeyboardButton("❌ REJECT", callback_data=f"OWNER_REJECT|{submission_id}|{worker_id}")
                        ]
                    ])

                    if photo:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo,
                            caption=caption,
                            reply_markup=keyboard
                        )
                    else:
                        await update.message.reply_text(
                            caption,
                            reply_markup=keyboard
                        )

                    if coords:
                        try:
                            lat, lon = map(float, coords.split(","))
                            await context.bot.send_location(
                                chat_id=update.effective_chat.id,
                                latitude=lat,
                                longitude=lon
                            )
                        except:
                            pass

            except Exception as e:
                log_block("PENDING LOAD ERROR")
                log_line("ERROR", repr(e))

            return
        if text == PANEL_BACK:
            await open_menu_for_role(update, context, role)
            return

        if text == PANEL_ACCOUNTS:
            await update.message.reply_text(
                "Accounts Menu",
                reply_markup=accounts_menu()
            )
            return

        if text == PANEL_ITEMS:
            await update.message.reply_text("📦 ITEMS panel opened")
            return

        if text == PANEL_WORKFLOW:

            if not POSTPONED_OWNER_SUBMISSIONS:
                await update.message.reply_text("No postponed owner submissions.")
                return

            for sid, data in POSTPONED_OWNER_SUBMISSIONS.items():

                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ APPROVE", callback_data=f"OWNER_APPROVE|{sid}"),
                        InlineKeyboardButton("❌ REJECT", callback_data=f"OWNER_REJECT|{sid}")
                    ]
                ])

                if data["photo"]:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=data["photo"],
                        caption=f"⏳ Postponed Submission\nSubmission ID: {sid}",
                        reply_markup=keyboard
                    )
                else:
                    await update.message.reply_text(
                        f"⏳ Postponed Submission {sid}",
                        reply_markup=keyboard
                    )

            return

        if text == PANEL_USERS:
            await update.message.reply_text("👥 USERS panel opened")
            return

        if text == PANEL_TASKS:
            await update.message.reply_text("📝 TASKS panel opened")
            return

        if text == PANEL_REPORTS:
            await update.message.reply_text("📊 REPORTS panel opened")
            return

        if text == PANEL_SYSTEM:
            await update.message.reply_text("⚙️ SYSTEM panel opened")
            return

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    if not query:
        return

    data = query.data

    if not data:
        return

    parts = data.split("|")
    action = parts[0]

    if action.startswith("OWNER_"):
        await owner_review_callback(update, context)
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

        await query.delete_message()

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
                await run_sheet(
                    context,
                    reject_owner_submission,
                    submission_id
                )

        except Exception as e:
            log_block("OWNER REJECT ERROR")
            log_line("ERROR", repr(e))

        await query.delete_message()

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

# =========================================================
# APP
# =========================================================
app = ApplicationBuilder().token(TOKEN).build()

DEBUG_MODE = True

app.add_handler(CallbackQueryHandler(callback_router))

# LOCATION MUST COME FIRST
# START must always work first
app.add_handler(CommandHandler("start", start_button), group=0)

# Then normal routing
app.add_handler(MessageHandler(filters.LOCATION, route_message), group=1)
app.add_handler(MessageHandler(~filters.COMMAND, route_message), group=2)

async def error_handler(update, context):
    log_block("GLOBAL ERROR")
    log_line("ERROR", repr(context.error))
    log_line("UPDATE", update)

app.add_error_handler(error_handler)

print("Bot running...")
app.run_polling(
    drop_pending_updates=True,
    poll_interval=0.1,
    timeout=30,
    bootstrap_retries=5,
)