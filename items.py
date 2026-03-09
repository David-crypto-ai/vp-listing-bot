from telegram import ReplyKeyboardMarkup, KeyboardButton
ffrom sheets_logger import create_draft, update_item_fields, get_worker_accounts
from utils import safe_text


# ================= ITEM STATES =================

ITEM_NONE = 0
ITEM_OWNER = 1
ITEM_PHOTOS = 2
ITEM_CAPTION = 3
ITEM_OWNER_PRICE = 4
ITEM_CONFIRM = 5


# ================= KEYBOARDS =================

def items_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📦 NEW ITEM")],
            [KeyboardButton("🗂️ MY ITEMS")],
            [KeyboardButton("🔙 BACK")]
        ],
        resize_keyboard=True
    )


def wizard_back_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔙 BACK")]
        ],
        resize_keyboard=True
    )


def confirm_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("✅ SAVE ITEM")],
            [KeyboardButton("❌ CANCEL")],
            [KeyboardButton("🔙 BACK")]
        ],
        resize_keyboard=True
    )


def owner_select_keyboard(accounts):

    rows = []

    for acc in accounts:

        label = f"{acc['owner_name']} ({acc['owner_id']})"

        rows.append([KeyboardButton(label)])

    rows.append([KeyboardButton("🔙 BACK")])

    return ReplyKeyboardMarkup(rows, resize_keyboard=True)
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("✅ SAVE ITEM")],
            [KeyboardButton("❌ CANCEL")],
            [KeyboardButton("🔙 BACK")]
        ],
        resize_keyboard=True
    )


# ================= MAIN HANDLER =================

async def handle_items_panel(update, context, text, role, status):

    from menus import PANEL_ITEMS

    uid = str(update.effective_user.id)

    # ---------------- OPEN ITEMS PANEL ----------------
    if text == PANEL_ITEMS and status == "ACTIVE":

        await update.message.reply_text(
            "📦 ITEMS PANEL",
            reply_markup=items_menu()
        )

        return True

    # ---------------- NEW ITEM ----------------
    if text == "📦 NEW ITEM" and status == "ACTIVE":

        accounts = get_worker_accounts(uid)

        if not accounts:

            await update.message.reply_text(
                "No accounts found. Please create an account first."
            )

            return True

        context.user_data["item_state"] = ITEM_OWNER
        context.user_data["item_draft"] = {
            "photos": []
        }

        context.user_data["owner_accounts"] = accounts

        await update.message.reply_text(
            "Select owner for this item:",
            reply_markup=owner_select_keyboard(accounts)
        )

        return True


    # ================= ITEM WIZARD =================

    state = context.user_data.get("item_state", ITEM_NONE)

    if state == ITEM_NONE:
        return False

    draft = context.user_data.get("item_draft", {})


    # =================================================
    # OWNER STEP
    # =================================================
    if state == ITEM_OWNER:

        if text == "🔙 BACK":

            context.user_data["item_state"] = ITEM_NONE
            context.user_data.pop("item_draft", None)

            await update.message.reply_text(
                "Back to items menu.",
                reply_markup=items_menu()
            )

            return True

        accounts = context.user_data.get("owner_accounts", [])

        selected_owner = None

        for acc in accounts:

            label = f"{acc['owner_name']} ({acc['owner_id']})"

            if text == label:
                selected_owner = acc
                break

        if not selected_owner:

            await update.message.reply_text(
                "Please select an owner from the list."
            )

            return True

        draft["owner_id"] = selected_owner["owner_id"]

        context.user_data["item_state"] = ITEM_PHOTOS

        await update.message.reply_text(
            "Send truck photos.\n\nSend one photo at a time.\nType DONE when finished.",
            reply_markup=wizard_back_keyboard()
        )

        return True


    # =================================================
    # PHOTO STEP
    # =================================================
    if state == ITEM_PHOTOS:

        if text == "🔙 BACK":

            context.user_data["item_state"] = ITEM_OWNER

            await update.message.reply_text(
                "Select owner for this item:",
                reply_markup=wizard_back_keyboard()
            )

            return True

        if text == "DONE":

            if not draft["photos"]:
                await update.message.reply_text(
                    "Please upload at least one photo."
                )
                return True

            context.user_data["item_state"] = ITEM_CAPTION

            await update.message.reply_text(
                "Send truck description or caption:",
                reply_markup=wizard_back_keyboard()
            )

            return True

        if update.message.photo:

            photo = update.message.photo[-1]

            draft["photos"].append(photo.file_id)

            await update.message.reply_text(
                f"Photo saved ({len(draft['photos'])})"
            )

            return True

        return True


    # =================================================
    # CAPTION STEP
    # =================================================
    if state == ITEM_CAPTION:

        if text == "🔙 BACK":

            context.user_data["item_state"] = ITEM_PHOTOS

            await update.message.reply_text(
                "Send truck photos again.\nType DONE when finished.",
                reply_markup=wizard_back_keyboard()
            )

            return True

        draft["caption"] = safe_text(text)

        context.user_data["item_state"] = ITEM_OWNER_PRICE

        await update.message.reply_text(
            "Enter owner price:",
            reply_markup=wizard_back_keyboard()
        )

        return True


    # =================================================
    # OWNER PRICE STEP
    # =================================================
    if state == ITEM_OWNER_PRICE:

        if text == "🔙 BACK":

            context.user_data["item_state"] = ITEM_CAPTION

            await update.message.reply_text(
                "Send description again:",
                reply_markup=wizard_back_keyboard()
            )

            return True

        draft["owner_price"] = safe_text(text)

        context.user_data["item_state"] = ITEM_CONFIRM

        await update.message.reply_text(
            f"""
Review Item

Owner ID: {draft.get("owner_id")}
Photos: {len(draft.get("photos", []))}
Owner Price: {draft.get("owner_price")}

Save item?
""",
            reply_markup=confirm_keyboard()
        )

        return True


    # =================================================
    # CONFIRM STEP
    # =================================================
    if state == ITEM_CONFIRM:

        if text == "🔙 BACK":

            context.user_data["item_state"] = ITEM_OWNER_PRICE

            await update.message.reply_text(
                "Enter owner price again:",
                reply_markup=wizard_back_keyboard()
            )

            return True

        if text == "❌ CANCEL":

            context.user_data["item_state"] = ITEM_NONE
            context.user_data.pop("item_draft", None)

            await update.message.reply_text(
                "Item creation cancelled.",
                reply_markup=items_menu()
            )

            return True

        if text == "✅ SAVE ITEM":

            item_id = create_draft(
                worker_id=uid,
                owner_id=draft.get("owner_id"),
                owner_type="Truck Owner",
                owner_name_cache=""
            )

            update_item_fields(
                item_id,
                {
                    "RAW_CAPTION": draft.get("caption"),
                    "PHOTO_COUNT": len(draft.get("photos")),
                    "OWNER_PRICE": draft.get("owner_price")
                }
            )

            # update owner recent usage timestamp
            from sheets_logger import owners_ws

            ws = owners_ws()
            rows = ws.get_all_values()

            for i, r in enumerate(rows[1:], start=2):

                if r and r[0] == draft.get("owner_id"):

                    ws.update_cell(i, 16, now_str())
                    break

            context.user_data["item_state"] = ITEM_NONE
            context.user_data.pop("item_draft", None)

            await update.message.reply_text(
                f"✅ Item created\n\nITEM_ID: {item_id}",
                reply_markup=items_menu()
            )

            return True

        return True


    return False