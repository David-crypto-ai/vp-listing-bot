import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from sheets_logger import add_test_row

TOKEN = os.environ["TELEGRAM_TOKEN"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot conectado correctamente ✅")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_test_row()
    await update.message.reply_text("Fila de prueba agregada a Google Sheets 📄")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("testsheet", test))

print("Bot running...")
app.run_polling()
