import os
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)

from telegram.error import Conflict

from accounts import start_button
from router import route_message, callback_router

TOKEN = os.environ["TELEGRAM_TOKEN"]

# ================= ERROR HANDLER =================
SECOND_BOT_WARNING_SHOWN = False

async def error_handler(update, context):

    global SECOND_BOT_WARNING_SHOWN

    if "terminated by other getUpdates request" in str(context.error):

        if not SECOND_BOT_WARNING_SHOWN:
            print("⚠ Another bot instance is polling Telegram")
            SECOND_BOT_WARNING_SHOWN = True

        raise context.error

    log_block("GLOBAL ERROR")
    log_line("ERROR", repr(context.error))
    log_line("UPDATE", update)

app = ApplicationBuilder().token(TOKEN).build()

print("Bot running...")
print("Polling started")
print("Waiting for updates...")

# ================= HANDLERS =================

app.add_handler(CallbackQueryHandler(callback_router))

app.add_handler(CommandHandler("start", start_button), group=0)

app.add_handler(MessageHandler(filters.LOCATION, route_message), group=1)

async def debug_router(update, context):

    if update.message:

        print("========== ROUTER DEBUG ==========")
        print("RAW_TEXT:", update.message.text)
        print("USER_ID:", update.effective_user.id)
        print("CHAT_ID:", update.effective_chat.id)
        print("USER_DATA_KEYS:", list(context.user_data.keys()))

    result = await route_message(update, context)

    print("ROUTER RESULT:", result)

    return result

app.add_handler(MessageHandler(~filters.COMMAND, debug_router), group=2)

# ================= TELEGRAM POLLING =================

try:
    app.bot.delete_webhook(drop_pending_updates=True)
except:
    pass

while True:

    try:
        print("Starting polling...")

        app.run_polling(
            drop_pending_updates=True,
            poll_interval=0.1,
            timeout=30,
            bootstrap_retries=5,
            allowed_updates=None
        )

    except Conflict:

        print("⚠ Conflict detected — another bot instance was polling.")
        print("Restarting polling in 3 seconds...")

        import time
        time.sleep(3)