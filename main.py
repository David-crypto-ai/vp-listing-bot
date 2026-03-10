import os
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)

from telegram.error import Conflict

from accounts import (
    start_button,
    route_message,
    callback_router
)

TOKEN = os.environ["TELEGRAM_TOKEN"]

# ================= ERROR HANDLER =================
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

    return await route_message(update, context)

app.add_handler(MessageHandler(~filters.COMMAND, debug_router), group=2)

# ================= TELEGRAM POLLING =================

import asyncio

async def clear_webhook():
    await app.bot.delete_webhook(drop_pending_updates=True)

asyncio.run(clear_webhook())

try:
    app.run_polling(
        drop_pending_updates=True,
        poll_interval=0.1,
        timeout=30,
        bootstrap_retries=5,
    )
except Conflict:
    print("Another bot instance detected. Restarting...")