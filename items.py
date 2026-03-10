from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from sheets_logger import create_draft, update_item_fields, get_worker_accounts
from utils import safe_text, now_str

def item_debug(label, value=""):
    print(f"[ITEM DEBUG] {label}: {value}")


# ================= ITEM STATES =================

ITEM_NONE = 0
ITEM_OWNER = 1
ITEM_VIN = 2
ITEM_OWNER_PRICE = 3
ITEM_PHOTOS = 4
ITEM_CAPTION = 5
ITEM_CONFIRM = 6


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


def duplicate_warning_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➡ CONTINUE")],
            [KeyboardButton("❌ CANCEL")]
        ],
        resize_keyboard=True
    )


# ================= REVIEW MEMORY =================

PENDING_ITEM_REVIEWS = {}
CURRENT_ITEM_REVIEW = {}

def owner_select_keyboard(accounts):

    rows = []

    for acc in accounts[:25]:

        label = f"{acc['owner_name']} ({acc['owner_id']})"

        rows.append([KeyboardButton(label)])

    rows.append([KeyboardButton("🔙 BACK")])

    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


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

    item_debug("state", state)
    item_debug("text", text)

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
        item_debug("owner_accounts_count", len(accounts))

        selected_owner = None

        for acc in accounts[:25]:

            label = f"{acc['owner_name']} ({acc['owner_id']})"
            item_debug("checking_owner_label", label)

            if text == label:
                selected_owner = acc
                item_debug("owner_matched", label)
                break

        if not selected_owner:

            item_debug("owner_match_failed", text)

            await update.message.reply_text(
                "Please select an owner from the list."
            )

            return True

        draft["owner_id"] = selected_owner["owner_id"]
        item_debug("owner_selected", draft["owner_id"])

        context.user_data["item_draft"] = draft
        context.user_data["item_state"] = ITEM_VIN

        await update.message.reply_text(
            "Enter full 17-digit VIN:",
            reply_markup=wizard_back_keyboard()
        )

        return True


    # =================================================
    # VIN STEP
    # =================================================
    if state == ITEM_VIN:

        if text == "🔙 BACK":

            context.user_data["item_state"] = ITEM_OWNER

            await update.message.reply_text(
                "Select owner again:",
                reply_markup=owner_select_keyboard(context.user_data.get("owner_accounts", []))
            )

            return True

        vin = safe_text(text).upper()

        if len(vin) != 17:

            await update.message.reply_text(
                "VIN must be 17 characters."
            )

            return True

        # duplicate check using TRUCK_INDEX
        from sheets_logger import index_ws

        idx = index_ws()

        vin_col = idx.col_values(2)[1:]  # VIN_FULL column

        for existing_vin in vin_col:

            existing_vin = (existing_vin or "").strip().upper()

            if existing_vin == vin:

                context.user_data["duplicate_vin"] = vin

                await update.message.reply_text(
                    "⚠ Possible duplicate VIN detected.\nContinue anyway?",
                    reply_markup=duplicate_warning_keyboard()
                )

                return True

        draft["vin"] = vin
        context.user_data["item_draft"] = draft
        context.user_data.pop("duplicate_vin", None)

        context.user_data["item_state"] = ITEM_PHOTOS

        await update.message.reply_text(
            "Upload truck photos.\nType DONE when finished.",
            reply_markup=wizard_back_keyboard()
        )

        return True


    # =================================================
    # DUPLICATE WARNING STEP
    # =================================================

    if context.user_data.get("duplicate_vin"):

        if text == "❌ CANCEL":

            context.user_data.pop("duplicate_vin", None)
            context.user_data["item_state"] = ITEM_VIN

            await update.message.reply_text(
                "Enter VIN again:",
                reply_markup=wizard_back_keyboard()
            )

            return True


        if text == "➡ CONTINUE":

            vin = context.user_data.pop("duplicate_vin")

            draft["vin"] = vin

            context.user_data["item_state"] = ITEM_PHOTOS

            await update.message.reply_text(
                "Upload truck photos.\nType DONE when finished.",
                reply_markup=wizard_back_keyboard()
            )

            return True


    # =================================================
    # PHOTO STEP
    # =================================================
    if state == ITEM_PHOTOS:

        if text == "🔙 BACK":

            context.user_data["item_state"] = ITEM_VIN

            await update.message.reply_text(
                "Enter full 17-digit VIN:",
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

            draft.setdefault("photos", [])
            draft["photos"].append(photo.file_id)

            await update.message.reply_text(
                f"Photo saved ({len(draft['photos'])})"
            )

            return True

        await update.message.reply_text(
            "Please send a photo or type DONE."
        )

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

        caption = safe_text(text).strip()
        draft["caption"] = caption

        # =========================
        # AUTO FIELD EXTRACTION
        # =========================

        import re

        year_match = re.search(r"(19|20)\d{2}", caption)
        if year_match:
            draft["year"] = year_match.group(0)

        make_match = re.search(r"(Peterbilt|Kenworth|Freightliner|Volvo|International|Mack)", caption, re.IGNORECASE)
        if make_match:
            draft["make"] = make_match.group(0)

        model_match = re.search(r"\b(389|579|379|579X|T680|W900)\b", caption)
        if model_match:
            draft["model"] = model_match.group(0)

        miles_match = re.search(r"(\d{3,6})\s?k?\s?miles", caption, re.IGNORECASE)
        if miles_match:

            miles = miles_match.group(1)

            if "k" in caption.lower():
                miles = int(miles) * 1000

            draft["miles"] = miles

        engine_match = re.search(r"(Detroit|Cummins|PACCAR)", caption, re.IGNORECASE)
        if engine_match:
            draft["engine"] = engine_match.group(0)

        context.user_data["item_draft"] = draft
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

        try:
            owner_price = float(safe_text(text).replace(",", ""))
        except:
            await update.message.reply_text(
                "Enter a valid number (example: 450000)"
            )
            return True

        if owner_price <= 400000:
            commission_rate = 0.10
        elif owner_price <= 500000:
            commission_rate = 0.09
        else:
            commission_rate = 0.08

        list_price = round(owner_price * (1 + commission_rate), 2)

        draft["owner_price"] = owner_price
        draft["list_price"] = list_price
        draft["commission_rate"] = commission_rate

        context.user_data["item_draft"] = draft
        context.user_data["item_state"] = ITEM_CONFIRM

        await update.message.reply_text(
            f"""
Review Item

Owner ID: {draft.get("owner_id")}
Photos: {len(draft.get("photos", []))}
Owner Price: {draft.get("owner_price")}
List Price: {draft.get("list_price")}
Commission: {draft.get("commission_rate")}

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
                    "VIN_FULL": draft.get("vin"),
                    "VIN_LAST6": draft.get("vin")[-6:] if draft.get("vin") else "",

                    "RAW_CAPTION": draft.get("caption"),
                    "PHOTO_COUNT": len(draft.get("photos")),

                    "YEAR": draft.get("year"),
                    "MAKE": draft.get("make"),
                    "MODEL": draft.get("model"),
                    "MILES": draft.get("miles"),
                    "ENGINE": draft.get("engine"),

                    "OWNER_PRICE": draft.get("owner_price"),
                    "LIST_PRICE": draft.get("list_price"),
                    "COMMISSION_RATE": draft.get("commission_rate")
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