import os
from telegram.ext import CallbackQueryHandler
from users import assign_role, register_user_pending, ensure_admin, get_user_status_role
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from sheets_logger import create_owner
from menus import (
    open_menu_for_role,
    accounts_menu,
    PANEL_ITEMS, PANEL_ACCOUNTS, PANEL_WORKFLOW, PANEL_USERS,
    PANEL_TASKS, PANEL_REPORTS, PANEL_SYSTEM, PANEL_BACK
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
SEEN_USERS = set()

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
ACCOUNT_OWNER_CITY = 4
ACCOUNT_OWNER_STATE = 5
ACCOUNT_CONFIRM = 6
ACCOUNT_LOCATION = 7
ACCOUNT_PHOTO = 13
ACCOUNT_EDIT_SELECT = 8
ACCOUNT_EDIT_NAME = 9
ACCOUNT_EDIT_PHONE = 10
ACCOUNT_EDIT_CITY = 11
ACCOUNT_EDIT_STATE = 12
ACCOUNT_BUSY = 99

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
    if role == "PENDING":
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
    context.user_data["account_state"] = ACCOUNT_OWNER_NAME
    context.user_data["account_draft"] = {"type": "WORKER"}
    context.user_data["cached_role"] = "REGISTERING"

    await update.message.reply_text(
        "Welcome 👋\nEnter your full name:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 CANCEL")]], resize_keyboard=True)
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
    if status == "ACTIVE" and state == ACCOUNT_NONE:

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

            if text == "👤 OWNER":
                context.user_data["account_state"] = ACCOUNT_OWNER_NAME
                context.user_data["account_draft"] = {"type": "OWNER"}

                await update.message.reply_text(
                    "Enter owner name:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
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

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_TYPE
                await update.message.reply_text(
                    "Select account type:",
                    reply_markup=ReplyKeyboardMarkup(
                        [
                            [KeyboardButton("👤 OWNER")],
                            [KeyboardButton("🌐 ONLINE")],
                            [KeyboardButton("🏛️ AUCTION")],
                            [KeyboardButton("🔙 BACK")]
                        ],
                        resize_keyboard=True
                    )
                )
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
            context.user_data["account_state"] = ACCOUNT_OWNER_STATE
            await update.message.reply_text(
                "Enter state:",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
            )
            return

        if state == ACCOUNT_OWNER_STATE:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_PHONE
                await update.message.reply_text(
                    "Enter phone number:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
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
                f"State: {draft.get('state','')}",
                reply_markup=confirm_keyboard()
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

                # Step 1: No location yet → go to location
                if "maps_link" not in draft:
                    context.user_data["account_state"] = ACCOUNT_LOCATION

                    keyboard = ReplyKeyboardMarkup(
                        [[KeyboardButton("📍 SEND LOCATION", request_location=True)],
                         [KeyboardButton("🔙 BACK")]],
                        resize_keyboard=True
                    )

                    await update.message.reply_text(
                        "Send the yard location pin:",
                        reply_markup=keyboard
                    )
                    return

                # Step 2: No photo yet → go to photo
                if "photo_file_id" not in draft:
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
                log_line("PHOTO_URL", draft.get("photo_url"))
                log_line("UID", uid)

                try:
                    if ENABLE_SHEETS:
                        await run_sheet(
                            context,
                            create_owner,
                            draft["type"],
                            draft["name"],
                            draft["phone"],
                            draft.get("city",""),
                            draft.get("state",""),
                            "",
                            draft.get("maps_link",""),
                            draft.get("photo_url",""),
                            uid
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
                    await update.message.reply_text(
                        "✅ Account created successfully.",
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
                    f"State: {draft.get('state','')}",
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
                f"State: {draft.get('state','')}",
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
                draft["city_state"] = draft.get("state", "")

                context.user_data["account_state"] = ACCOUNT_PHOTO

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

                context.user_data["account_state"] = ACCOUNT_CONFIRM

                await update.message.reply_text(
                    f"Review account:\n"
                    f"Type: {draft['type']}\n"
                    f"Name: {draft['name']}\n"
                    f"Phone: {draft['phone']}\n"
                    f"State: {draft.get('state','')}\n"
                    f"Location: ✅\n"
                    f"Photo: ✅",
                    reply_markup=confirm_keyboard()
                )
                return

            await update.message.reply_text("Please send a photo.")
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
        context.user_data["account_draft"] = {}

        keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("👤 OWNER")],
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
            await update.message.reply_text("🔄 WORKFLOW panel opened")
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

async def approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split("|")

    if len(parts) < 2:
        return

    action = parts[0]
    target_id = parts[1]
    admin_id = str(query.from_user.id)
    from config import ADMIN_IDS

    # 🚫 Only admins can approve users
    if admin_id not in ADMIN_IDS:
        await query.edit_message_text("⛔ You are not allowed to approve users.")
        return

    # ================= APPROVE =================
    if action == "APPROVE":
        if len(parts) < 3:
            await query.edit_message_text("❌ Invalid approval data")
            return

        role = parts[2]

        # BOTH = FINDER + SELLER
        if role == "BOTH":
            await run_sheet(context, assign_role, target_id, "FINDER", admin_id)
            await run_sheet(context, assign_role, target_id, "SELLER", admin_id)
            role_text = "FINDER + SELLER"
        else:
            await run_sheet(context, assign_role, target_id, role, admin_id)
            role_text = role

        # update cache immediately (prevents START loop)
        ROLE_CACHE[target_id] = (role_text if role != "BOTH" else "FINDER", "ACTIVE")

        # force next message to reopen menu
        context.application.bot_data.setdefault("force_role_cache", {})[target_id] = ROLE_CACHE[target_id]

        await query.edit_message_text(
            f"✅ User {target_id} approved as {role_text}"
        )

        # 🔔 Notify the approved user
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 Your account has been approved!\nSend any message to open your workspace."
            )

        except Exception:
            pass

    # ================= REJECT =================
    elif action == "REJECT":
        await query.edit_message_text(
            f"❌ User {target_id} rejected"
        )

# =========================================================
# APP
# =========================================================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.ALL, debug_all), group=-1)

app.add_handler(CallbackQueryHandler(approval_callback))

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