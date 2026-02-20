import os
from telegram.ext import CallbackQueryHandler
from users import assign_role
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from sheets_logger import create_draft
from users import register_user_pending, ensure_admin, get_user_status_role
from menus import (
    open_menu_for_role,
    PANEL_ITEMS, PANEL_ACCOUNTS, PANEL_WORKFLOW, PANEL_USERS,
    PANEL_TASKS, PANEL_REPORTS, PANEL_SYSTEM, PANEL_BACK
)

TOKEN = os.environ["TELEGRAM_TOKEN"]

ROLE_CACHE = {}
ADMIN_CACHE = set()

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
ACCOUNT_CONFIRM = 5
ACCOUNT_LOCATION = 6
ACCOUNT_EDIT_SELECT = 7
ACCOUNT_EDIT_NAME = 8
ACCOUNT_EDIT_PHONE = 9
ACCOUNT_EDIT_CITY = 10
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

async def run_sheet(context, func, *args, **kwargs):
    return await context.application.run_in_threadpool(func, *args, **kwargs)

# =========================================================
# FIRST CONTACT (shows START button only once)
# =========================================================
async def first_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("▶ START")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Press START to open the system",
        reply_markup=reply_markup
    )

# =========================================================
# START BUTTON PRESSED
# =========================================================
async def start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "▶ START":
        return

    user = update.effective_user

    # --- ADMIN AUTO UNLOCK ---
    if str(user.id) in ADMIN_CACHE:
        is_admin = True
    else:
        is_admin = await run_sheet(context, ensure_admin, str(user.id), user.username or "", user.full_name)
        if is_admin:
            ADMIN_CACHE.add(str(user.id))

    if is_admin:
        # cache admin role immediately (no sheets re-check)
        ROLE_CACHE[str(user.id)] = ("ADMIN", "ACTIVE")
        context.user_data["cached_role"] = "ADMIN"
        ADMIN_CACHE.add(str(user.id))

        await update.message.reply_text(
            "🔓 Admin access granted",
            reply_markup=base_nav_keyboard()
        )

        await open_menu_for_role(update, context, "ADMIN")
        return

    # --- NORMAL USERS ---
    created = await run_sheet(
        context,
        register_user_pending,
        telegram_id=str(user.id),
        username=user.username or "",
        full_name=user.full_name
    )

    if created:
        from users import notify_admin_new_user
        await notify_admin_new_user(context, str(user.id), user.username or "", user.full_name)

    await update.message.reply_text(
        "Welcome 👋\n"
        "Your account has been registered in the system.\n"
        "Waiting for administrator approval.",
        reply_markup=base_nav_keyboard()
    )

# =========================================================
# MAIN MESSAGE ROUTER
# =========================================================
async def route_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    text = update.message.text or ""
    user = update.effective_user

    # --- START BUTTON ---
    if text == "▶ START":
        await start_button(update, context)
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
        role, status = await get_cached_role(context, str(user.id))
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
            context.user_data["account_state"] = ACCOUNT_OWNER_CITY
            await update.message.reply_text(
                "Enter city:",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
            )
            return

        # --- OWNER CITY ---
        if state == ACCOUNT_OWNER_CITY:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_PHONE
                await update.message.reply_text("Enter phone number:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True))
                return

            context.user_data["account_draft"]["city"] = text
            context.user_data["account_state"] = ACCOUNT_CONFIRM

            draft = context.user_data["account_draft"]

            await update.message.reply_text(
                f"Review account:\n"
                f"Type: {draft['type']}\n"
                f"Name: {draft['name']}\n"
                f"Phone: {draft['phone']}\n"
                f"City: {draft['city']}",
                reply_markup=confirm_keyboard()
            )
            return

        # --- CONFIRMATION STEP ---
        if state == ACCOUNT_CONFIRM:

            if text == "❌ CANCEL":
                clear_user_session(context)
                await open_menu_for_role(update, context, role)
                return

            if text == "✏ EDIT":
                context.user_data["account_state"] = ACCOUNT_EDIT_SELECT
                await update.message.reply_text(
                    "Select field to edit:",
                    reply_markup=edit_menu_keyboard()
                )
                return

            if text == "✅ CONFIRM":
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
                    f"City: {draft['city']}",
                    reply_markup=confirm_keyboard()
                )
                return

            return


        # ================= APPLY EDIT =================
        if state in [ACCOUNT_EDIT_NAME, ACCOUNT_EDIT_PHONE, ACCOUNT_EDIT_CITY]:

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

            context.user_data["account_state"] = ACCOUNT_CONFIRM
            draft = context.user_data["account_draft"]

            await update.message.reply_text(
                f"Review account:\n"
                f"Type: {draft['type']}\n"
                f"Name: {draft['name']}\n"
                f"Phone: {draft['phone']}\n"
                f"City: {draft['city']}",
                reply_markup=confirm_keyboard()
            )
            return

        # ================= LOCATION CAPTURE =================
        if state == ACCOUNT_LOCATION:

            # allow escape
            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_CONFIRM
                await update.message.reply_text("Back to review:", reply_markup=confirm_keyboard())
                return

            if update.message.location:
                lock_user(context)

                loc = update.message.location
                draft = context.user_data.setdefault("account_draft", {})
                draft["lat"] = loc.latitude
                draft["lng"] = loc.longitude

                context.application.create_task(
                    run_sheet(context, create_draft, str(user.id), draft)
                )

                await update.message.reply_text(
                    f"Location saved:\n"
                    f"{draft.get('name','')} ({draft.get('city','')})\n"
                    f"Lat: {draft.get('lat','')}\n"
                    f"Lng: {draft.get('lng','')}",
                    reply_markup=base_nav_keyboard()
                )

                clear_user_session(context)
                await open_menu_for_role(update, context, role)
                return

            else:
                await update.message.reply_text("Please send the location using the button.")
                return

    # ================= ADMIN PANEL NAVIGATION =================
    if role == "ADMIN":

        if text == PANEL_BACK:
            await open_menu_for_role(update, context, role)
            return

        if text == PANEL_ITEMS:
            await update.message.reply_text("📦 ITEMS panel opened")
            return

        if text == PANEL_ACCOUNTS:
            context.user_data["account_state"] = ACCOUNT_TYPE

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

    # --- OPEN MENU ONLY WHEN USER ASKS ---
    if text in ["🏠 MENU", "🔙 BACK", "OPEN MENU"]:
        await open_menu_for_role(update, context, role)
        return

# =========================================================
# TEST SHEET
# =========================================================
async def testsheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await run_sheet(context, create_draft, str(update.effective_user.id), "manual test")
    await update.message.reply_text("Draft created 📄")

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

        ROLE_CACHE.pop(target_id, None)

        await query.edit_message_text(
            f"✅ User {target_id} approved as {role_text}"
        )

        # 🔔 Notify the approved user
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 Your account has been approved!\nPress 🏠 MENU to begin."
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

app.add_handler(CallbackQueryHandler(approval_callback))

# LOCATION MUST COME FIRST
app.add_handler(MessageHandler(filters.LOCATION, route_message), group=0)
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, route_message), group=1)

app.add_handler(CommandHandler("start", first_contact))
app.add_handler(CommandHandler("testsheet", testsheet))

print("Bot running...")
app.run_polling(
    drop_pending_updates=True,
    poll_interval=0.1,
    timeout=10,
)