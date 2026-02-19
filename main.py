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

def base_nav_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🏠 MENU")]],
        resize_keyboard=True
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

    text = update.message.text
    user = update.effective_user

    # --- START BUTTON ---
    if text == "▶ START":
        await start_button(update, context)
        return

    # --- CHECK ROLE ---
    role, status = get_user_status_role(str(user.id))

    if status != "ACTIVE":
        await update.message.reply_text("⏳ Waiting for administrator approval.")
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
            await update.message.reply_text("🏢 ACCOUNTS panel opened")
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

    if action == "APPROVE":
        role = parts[2]
        assign_role(target_id, role, admin_id)

        await query.edit_message_text(
            f"✅ User {target_id} approved as {role}"
        )

        # 🔔 Notify the approved user
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 Your account has been approved!\nPress 🏠 MENU to begin."
            )
        except Exception:
            pass

    elif action == "REJECT":
        await query.edit_message_text(
            f"❌ User {target_id} rejected"
        )

# =========================================================
# APP
# =========================================================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CallbackQueryHandler(approval_callback))
# Order matters!
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, route_message))
app.add_handler(CommandHandler("start", first_contact))
app.add_handler(CommandHandler("testsheet", testsheet))

print("Bot running...")
app.run_polling(drop_pending_updates=True)
