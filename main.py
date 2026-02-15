import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from sheets_logger import create_draft

TOKEN = os.environ["TELEGRAM_TOKEN"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot conectado correctamente ✅")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    create_draft(str(update.effective_user.id), "manual test")
    await update.message.reply_text("Registro creado en la base de datos 📄")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("testsheet", test))

print("Bot running...")
app.run_polling(drop_pending_updates=True)
