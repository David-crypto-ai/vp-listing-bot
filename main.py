import os
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from sheets_logger import create_draft
from users import register_user

TOKEN = os.environ["TELEGRAM_TOKEN"]

# ---------------- START BUTTON KEYBOARD ----------------
start_keyboard = ReplyKeyboardMarkup(
    [[KeyboardButton("▶ START")]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# ---------------- FIRST MESSAGE (no commands shown) ----------------
async def first_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Press START to open the system",
        reply_markup=start_keyboard
    )

# ---------------- WHEN USER PRESSES START ----------------
async def start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "▶ START":
        return

    user = update.effective_user

    register_user(
        telegram_id=str(user.id),
        username=user.username or "",
        full_name=user.full_name
    )

    await update.message.reply_text(
        "Welcome 👋\n"
        "Your account has been registered in the system.\n"
        "Waiting for administrator approval."
    )

# ---------------- TEST COMMAND ----------------
async def testsheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    create_draft(str(update.effective_user.id), "manual test")
    await update.message.reply_text("Draft created 📄")

# ---------------- APP ----------------
app = ApplicationBuilder().token(TOKEN).build()

# Only /start exists — and only shows button
app.add_handler(CommandHandler("start", first_contact))

# Button press listener
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start_button))

# test command
app.add_handler(CommandHandler("testsheet", testsheet))

print("Bot running...")
app.run_polling(drop_pending_updates=True)
