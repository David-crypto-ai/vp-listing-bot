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

# =========================================================
# UI LOCK (FOCUS LOCK)
# =========================================================
GLOBAL_NAV_BUTTONS = {
    "🏠 MENU",
    "OPEN MENU",
    PANEL_ITEMS,
    PANEL_ACCOUNTS,
    PANEL_WORKFLOW,
    PANEL_USERS,
    PANEL_TASKS,
    PANEL_REPORTS,
    PANEL_SYSTEM
}

def is_global_nav_press(text: str) -> bool:
    return text in GLOBAL_NAV_BUTTONS

async def block_nav_during_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Do NOT replace keyboard — just show warning
    await update.message.reply_text(
        "🔒 Finish the current step first."
    )

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
    if ensure_admin(str(user.id), user.username or "", user.full_name):
        await update.message.reply_text(
            "🔓 Admin access granted",
            reply_markup=base_nav_keyboard()
        )

        role, status = get_user_status_role(str(user.id))
        await open_menu_for_role(update, context, role)
        return

    # --- NORMAL USERS ---
    created = register_user_pending(
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

    text = update.message.text if update.message.text else ""
    user = update.effective_user

    # --- START BUTTON ---
    if text == "▶ START":
        await start_button(update, context)
        return

    # --- CHECK ROLE ---
    role, status = get_user_status_role(str(user.id))

    if status != "ACTIVE":

        # allow menu access while pending
        if text in ["🏠 MENU", "OPEN MENU"]:
            await update.message.reply_text("⏳ Waiting for administrator approval.")
            return

        await update.message.reply_text("⏳ Waiting for administrator approval.")
        return

    # ================= ACCOUNT WIZARD HANDLER =================
    state = context.user_data.get("account_state", ACCOUNT_NONE)

    # ✅ FOCUS LOCK: block all global navigation while inside wizard
    # This prevents "ITEMS / USERS / WORKFLOW / MENU" from hijacking wizard input.
    if state != ACCOUNT_NONE and state != ACCOUNT_BUSY:
        if is_global_nav_press(text):
            await block_nav_during_wizard(update, context)
            return

    if state != ACCOUNT_NONE:

        if state == ACCOUNT_BUSY:
            return

        # --- SELECT TYPE ---
        if state == ACCOUNT_TYPE:

            if "OWNER" in text:
                context.user_data["account_state"] = ACCOUNT_OWNER_NAME
                context.user_data["account_draft"] = {"type": "OWNER"}
                await update.message.reply_text("Enter owner name:")
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
            context.user_data["account_draft"]["name"] = text
            context.user_data["account_state"] = ACCOUNT_OWNER_PHONE
            await update.message.reply_text("Enter phone number:")
            return

        # --- OWNER PHONE ---
        if state == ACCOUNT_OWNER_PHONE:
            context.user_data["account_draft"]["phone"] = text
            context.user_data["account_state"] = ACCOUNT_OWNER_CITY
            await update.message.reply_text("Enter city:")
            return

        # --- OWNER CITY (END) ---
        if state == ACCOUNT_OWNER_CITY:
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
                context.user_data["account_state"] = ACCOUNT_NONE
                context.user_data.pop("account_draft", None)
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
                    [[KeyboardButton("📍 SEND LOCATION", request_location=True)]],
                    resize_keyboard=True,
                    one_time_keyboard=True
                )

                await update.message.reply_text(
                    "Send the yard location pin:",
                    reply_markup=keyboard
                )
                return

            await update.message.reply_text("Use the buttons below.")
            return

        # ================= EDIT SELECT =================
        if state == ACCOUNT_EDIT_SELECT:

            if text == "Name":
                context.user_data["account_state"] = ACCOUNT_EDIT_NAME
                await update.message.reply_text("Enter new name:")
                return

            if text == "Phone":
                context.user_data["account_state"] = ACCOUNT_EDIT_PHONE
                await update.message.reply_text("Enter new phone:")
                return

            if text == "City":
                context.user_data["account_state"] = ACCOUNT_EDIT_CITY
                await update.message.reply_text("Enter new city:")
                return

            if text == "Location":
                context.user_data["account_state"] = ACCOUNT_LOCATION
                keyboard = ReplyKeyboardMarkup(
                    [[KeyboardButton("📍 SEND LOCATION", request_location=True)]],
                    resize_keyboard=True,
                    one_time_keyboard=True
                )
                await update.message.reply_text("Send new location:", reply_markup=keyboard)
                return

            if "BACK" in text:
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

            # ignore any other text while selecting edit field
            await update.message.reply_text("Choose one of the buttons.")
            return

        # ================= APPLY EDIT =================
        if state in [ACCOUNT_EDIT_NAME, ACCOUNT_EDIT_PHONE, ACCOUNT_EDIT_CITY]:

            lock_user(context)

            if state == ACCOUNT_EDIT_NAME:
                context.user_data["account_draft"]["name"] = text

            elif state == ACCOUNT_EDIT_PHONE:
                context.user_data["account_draft"]["phone"] = text

            elif state == ACCOUNT_EDIT_CITY:
                context.user_data["account_draft"]["city"] = text

            unlock_user(context, ACCOUNT_CONFIRM)

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
            if text in ["🏠 MENU", "🔙 BACK"]:
                context.user_data["account_state"] = ACCOUNT_NONE
                context.user_data.pop("account_draft", None)
                await open_menu_for_role(update, context, role)
                return

            if update.message.location:
                lock_user(context)

                loc = update.message.location
                context.user_data["account_draft"]["lat"] = loc.latitude
                context.user_data["account_draft"]["lng"] = loc.longitude

                draft = context.user_data["account_draft"]

                await update.message.reply_text(
                    f"Location saved:\n"
                    f"{draft['name']} ({draft['city']})\n"
                    f"Lat: {draft['lat']}\n"
                    f"Lng: {draft['lng']}",
                    reply_markup=base_nav_keyboard()
                )

                context.user_data["account_state"] = ACCOUNT_NONE
                context.user_data.pop("account_draft", None)

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
    create_draft(str(update.effective_user.id), "manual test")
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
            assign_role(target_id, "FINDER", admin_id)
            assign_role(target_id, "SELLER", admin_id)
            role_text = "FINDER + SELLER"
        else:
            assign_role(target_id, role, admin_id)
            role_text = role

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
app.add_handler(MessageHandler(filters.LOCATION, route_message))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, route_message))

app.add_handler(CommandHandler("start", first_contact))
app.add_handler(CommandHandler("testsheet", testsheet))

print("Bot running...")
app.run_polling(drop_pending_updates=True)