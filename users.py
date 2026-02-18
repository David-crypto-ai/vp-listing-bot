from telegram import Update
from telegram.ext import ContextTypes
from sheets_logger import user_exists, add_pending_user

ADMIN_ID = 587441233  # <-- change to your telegram id

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user_exists(user.id):
        await update.message.reply_text("Welcome back ✅")
        return

    add_pending_user(user)

    await update.message.reply_text("Your access request was sent to admin ⏳")

    # notify admin
    await context.bot.send_message(
        ADMIN_ID,
        f"""New user request:

Name: {user.full_name}
Username: @{user.username}
ID: {user.id}

Approve inside Google Sheet → USERS tab"""
    )
