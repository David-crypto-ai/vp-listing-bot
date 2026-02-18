import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from sheets_logger import create_draft
from users import register_user

TOKEN = os.environ["TELEGRAM_TOKEN"]


# ---------------- START / REGISTER ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


# ---------------- TEST SHEET ----------------
async def testsheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    create_draft(str(update.effective_user.id), "manual test")

    await update.message.reply_text(
        "Draft item created in database 📄"
    )


# ---------------- BOT START ----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("testsheet", testsheet))

    print("Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
