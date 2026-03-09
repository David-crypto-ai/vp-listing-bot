async def handle_items_panel(update, context, text, role, status):

    from menus import PANEL_ITEMS

    if text == PANEL_ITEMS and status == "ACTIVE":

        await update.message.reply_text(
            "📦 ITEMS panel opened"
        )

        return True

    return False