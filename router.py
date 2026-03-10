from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram import InputMediaPhoto
from telegram.ext import ContextTypes
from accounts import log_block, log_line

from menus import (
    open_menu_for_role,
    accounts_menu,
    PANEL_ITEMS, PANEL_ACCOUNTS, PANEL_WORKFLOW, PANEL_USERS,
    PANEL_TASKS, PANEL_REPORTS, PANEL_SYSTEM, PANEL_BACK,
    BTN_PENDING_ACCOUNTS
)

from items import handle_items_panel

from accounts import (
    get_cached_role,
    STATE_LIST,
    ACCOUNT_NONE,
    ACCOUNT_TYPE,
    ACCOUNT_OWNER_NAME,
    ACCOUNT_OWNER_PHONE,
    ACCOUNT_OWNER_EMAIL,
    ACCOUNT_OWNER_SOCIALS,
    ACCOUNT_OWNER_CITY,
    ACCOUNT_OWNER_STATE,
    ACCOUNT_CONFIRM,
    ACCOUNT_LOCATION,
    ACCOUNT_PHOTO,
    ACCOUNT_DUPLICATE_CHECK,
    ACCOUNT_EDIT_SELECT,
    ACCOUNT_EDIT_NAME,
    ACCOUNT_EDIT_PHONE,
    ACCOUNT_EDIT_CITY,
    ACCOUNT_EDIT_STATE,
    ACCOUNT_BUSY,
    clear_user_session,
    state_keyboard,
    confirm_keyboard,
    edit_menu_keyboard,
    base_nav_keyboard,
    lock_user,
    unlock_user,
    run_sheet,
    ROLE_CACHE,
    USER_RATE_LIMIT,
    RATE_LIMIT_SECONDS,
    POSTPONED_OWNER_SUBMISSIONS,
    ADMIN_CACHE
)

from sheets_logger import (
    create_owner_submission,
    check_nearby_accounts,
    get_pending_owner_submissions
)

from config import ADMIN_IDS
import time

async def route_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    # capture message text safely (buttons, captions, etc)
    raw_text = (update.message.text or update.message.caption or "").strip()

    # detect photos early (important for item uploads)
    has_photo = bool(update.message.photo)

    # normalized button version (safe for comparisons)
    btn = (
        raw_text.upper()
        .replace("➡️", "")
        .replace("➡", "")
        .replace("❌", "")
        .replace("✅", "")
        .replace("🔙", "")
        .replace("📍", "")
        .replace("⏳", "")
        .strip()
    )

    # keep raw text for real user input
    text = raw_text.strip()

    # prevent router from resetting menu when photo is sent
    if has_photo and not text:
        text = "__PHOTO__"

    log_block("BUTTON DEBUG")
    log_line("RAW_TEXT", raw_text)
    log_line("BUTTON_TEXT", btn)

    if not text and update.message.caption:
        text = update.message.caption.strip()

    uid = str(update.effective_user.id)
    user = update.effective_user

    # ===== USER RATE LIMIT =====
    import time
    now = time.time()

    last = USER_RATE_LIMIT.get(uid)

    # allow BACK and PHOTO uploads to bypass rate limiter
    if btn != "BACK" and not has_photo:
        if last and now - last < RATE_LIMIT_SECONDS:
            return

        USER_RATE_LIMIT[uid] = now

    # session warm-start after approval (VERY IMPORTANT FIRST)
    forced = context.application.bot_data.get("force_role_cache", {}).pop(str(user.id), None)
    if forced:
        ROLE_CACHE[str(user.id)] = forced

    # allow known approved users even if cache restarted
    # if wizard active, avoid Google Sheets lookup
    if context.user_data.get("account_state", ACCOUNT_NONE) != ACCOUNT_NONE:
        role = context.user_data.get("cached_role")
        status = "ACTIVE"
    else:
        role, status = await get_cached_role(context, uid)

    # ===== AUTO SESSION RECOVERY (CRITICAL) =====
    state = context.user_data.get("account_state", ACCOUNT_NONE)

    # ACTIVE USERS → reopen menu only if user typed random text
    if (
        status == "ACTIVE"
        and state == ACCOUNT_NONE
        and not context.user_data.get("account_draft")
        and not context.user_data.get("item_state")
    ):

        # always refresh role menu after updates
        context.user_data["cached_role"] = role

        # allow ITEM buttons to pass through router
        if text not in [
            PANEL_ACCOUNTS,
            PANEL_ITEMS,
            PANEL_WORKFLOW,
            PANEL_USERS,
            PANEL_TASKS,
            PANEL_REPORTS,
            PANEL_SYSTEM,
            PANEL_BACK,
            "📦 NEW ITEM",
            "🗂️ MY ITEMS",
            "➕ ADD ACCOUNT",
            "👤 MY ACCOUNTS",
            "📍 NEARBY ACCOUNTS",
            "🔎 SEARCH ACCOUNT",
            BTN_PENDING_ACCOUNTS
        ]:
            await open_menu_for_role(update, context, role)
            return

    # PENDING USERS → always inform
    if status == "PENDING":
        await update.message.reply_text("⏳ Waiting for administrator approval.")
        return

    # REGISTERING USERS (cache lost after restart)
    if status not in ["ACTIVE", "PENDING"] and state == ACCOUNT_NONE:
        context.user_data["account_state"] = ACCOUNT_OWNER_NAME
        context.user_data["account_draft"] = {"type": "WORKER"}
        context.user_data["cached_role"] = "REGISTERING"
        await update.message.reply_text("Let's continue your registration.\nEnter your full name:")
        return
    # ================= ACCOUNT WIZARD HANDLER =================
    state = context.user_data.get("account_state", ACCOUNT_NONE)

    if state != ACCOUNT_NONE:
        # wizard active → use cached role, never query sheets
        role = context.user_data.get("cached_role")
        status = "ACTIVE"

        # fallback only if cache missing (prevents "stuck")
        if not role:
            role, _status = await get_cached_role(context, str(user.id))
            context.user_data["cached_role"] = role
    else:
        context.user_data["cached_role"] = role

        if status != "ACTIVE":
            await update.message.reply_text("⏳ Waiting for administrator approval.")
            return


    # ================= WIZARD STATES =================
    if state != ACCOUNT_NONE:

        # wizard safety guard
        if "account_draft" not in context.user_data:
            context.user_data["account_state"] = ACCOUNT_NONE
            return

        if state == ACCOUNT_BUSY:
            return

        # --- SELECT TYPE ---
        if state == ACCOUNT_TYPE:

            if btn == "LOCATION":

                context.user_data["account_state"] = ACCOUNT_LOCATION
                context.user_data["account_draft"] = {
                    "type": "OWNER",
                    "distance_warning": ""
                }

                keyboard = ReplyKeyboardMarkup(
                    [
                        [KeyboardButton("📍 SEND LOCATION", request_location=True)],
                        [KeyboardButton("🔙 BACK")]
                    ],
                    resize_keyboard=True
                )

                await update.message.reply_text(
                    "Please send the yard location using the button:",
                    reply_markup=keyboard
                )
                return

            if "ONLINE" in text:
                await update.message.reply_text("Online accounts coming soon")
                return

            if "AUCTION" in text:
                await update.message.reply_text("Auction accounts coming soon")
                return

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_NONE
                await open_menu_for_role(update, context, role)
                return

            return

        # --- OWNER NAME ---
        if state == ACCOUNT_OWNER_NAME:

            if btn == "CONTINUE":
                return

            if btn == "BACK":
                context.user_data["account_state"] = ACCOUNT_TYPE
                await update.message.reply_text(
                    "Select account type:",
                    reply_markup=ReplyKeyboardMarkup(
                        [
                            [KeyboardButton("📍 LOCATION")],
                            [KeyboardButton("🌐 ONLINE")],
                            [KeyboardButton("🏛️ AUCTION")],
                            [KeyboardButton("🔙 BACK")]
                        ],
                        resize_keyboard=True
                    )
                )
                return

            context.user_data.setdefault("account_draft", {})["name"] = raw_text
            context.user_data["account_state"] = ACCOUNT_OWNER_PHONE

            await update.message.reply_text(
                "Enter phone number:",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
            )
            return

        # --- OWNER PHONE ---
        if state == ACCOUNT_OWNER_PHONE:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_NAME
                await update.message.reply_text("Enter owner name:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True))
                return

            context.user_data["account_draft"]["phone"] = text
            context.user_data["account_state"] = ACCOUNT_OWNER_EMAIL

            await update.message.reply_text(
                "Enter email (optional):",
                reply_markup=ReplyKeyboardMarkup(
                    [
                        [KeyboardButton("➡ NEXT")],
                        [KeyboardButton("🔙 BACK")]
                    ],
                    resize_keyboard=True
                )
            )
            return

        if state == ACCOUNT_OWNER_STATE:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_CITY
                await update.message.reply_text(
                    "Enter city:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "MEXICO":
                await update.message.reply_text(
                    "Select state:",
                    reply_markup=state_keyboard("MEXICO")
                )
                return

            if text == "USA":
                await update.message.reply_text(
                    "Select state:",
                    reply_markup=state_keyboard("USA")
                )
                return

            matches = [s for s in STATE_LIST if s.startswith(text)]

            if len(matches) > 1:
                await update.message.reply_text(
                    "Select state:",
                    reply_markup=state_keyboard(filter_text=text)
                )
                return

            if text not in STATE_LIST:
                await update.message.reply_text(
                    "Please select a state from the list or type the first letters.",
                    reply_markup=state_keyboard()
                )
                return

            context.user_data["account_draft"]["state"] = text
            context.user_data["account_state"] = ACCOUNT_CONFIRM

            draft = context.user_data["account_draft"]

            await update.message.reply_text(
                f"Review account:\n"
                f"Type: {draft.get('type','')}\n"
                f"Name: {draft.get('name','')}\n"
                f"Phone: {draft.get('phone','')}\n"
                f"City/State: {draft.get('city','') + ', ' if draft.get('city') else ''}{draft.get('state','')}",
                reply_markup=confirm_keyboard()
            )
            return
        
        if state == ACCOUNT_OWNER_EMAIL:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_PHONE
                await update.message.reply_text(
                    "Enter phone number:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "➡ NEXT":
                context.user_data["account_draft"]["email"] = ""
            else:
                context.user_data["account_draft"]["email"] = text

            context.user_data["account_state"] = ACCOUNT_OWNER_SOCIALS

            await update.message.reply_text(
                "Enter social media links (optional):",
                reply_markup=ReplyKeyboardMarkup(
                    [
                        [KeyboardButton("➡ NEXT")],
                        [KeyboardButton("🔙 BACK")]
                    ],
                    resize_keyboard=True
                )
            )
            return
        if state == ACCOUNT_OWNER_SOCIALS:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_EMAIL
                await update.message.reply_text(
                    "Enter email (optional):",
                    reply_markup=ReplyKeyboardMarkup(
                        [
                            [KeyboardButton("➡ NEXT")],
                            [KeyboardButton("🔙 BACK")]
                        ],
                        resize_keyboard=True
                    )
                )
                return

            if text == "➡ NEXT":
                context.user_data["account_draft"]["socials"] = ""
            else:
                context.user_data["account_draft"]["socials"] = text

            context.user_data["account_state"] = ACCOUNT_OWNER_CITY

            await update.message.reply_text(
                "Enter city (optional):",
                reply_markup=ReplyKeyboardMarkup(
                    [
                        [KeyboardButton("➡ NEXT")],
                        [KeyboardButton("🔙 BACK")]
                    ],
                    resize_keyboard=True
                )
            )
            return
            
        # --- OWNER CITY ---
        if state == ACCOUNT_OWNER_CITY:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_OWNER_SOCIALS
                await update.message.reply_text(
                    "Enter social media links (optional):",
                    reply_markup=ReplyKeyboardMarkup(
                        [
                            [KeyboardButton("➡ NEXT")],
                            [KeyboardButton("🔙 BACK")]
                        ],
                        resize_keyboard=True
                    )
                )
                return

            if text == "➡ NEXT":
                context.user_data["account_state"] = ACCOUNT_OWNER_STATE

                await update.message.reply_text(
                    "Select state:",
                    reply_markup=state_keyboard()
                )
                return

            context.user_data["account_draft"]["city"] = text
            context.user_data["account_state"] = ACCOUNT_OWNER_STATE

            await update.message.reply_text(
                "Select state:",
                reply_markup=state_keyboard()
            )
            return

        # --- CONFIRMATION STEP ---
        if state == ACCOUNT_CONFIRM:

            if "CANCEL" in text:
                clear_user_session(context)
                await open_menu_for_role(update, context, role)
                return

            if "EDIT" in text:
                context.user_data["account_state"] = ACCOUNT_EDIT_SELECT
                await update.message.reply_text(
                    "Select field to edit:",
                    reply_markup=edit_menu_keyboard()
                )
                return

            if "CONFIRM" in text:

                draft = context.user_data["account_draft"]

                # Step 1: Ensure photo exists
                if not draft.get("photo_file_id"):

                    context.user_data["account_state"] = ACCOUNT_PHOTO

                    await update.message.reply_text(
                        "📸 Now send a yard photo:",
                        reply_markup=ReplyKeyboardMarkup(
                            [[KeyboardButton("🔙 BACK")]],
                            resize_keyboard=True
                        )
                    )
                    return

                # Step 3: Everything collected → SAVE
                lock_user(context)
                save_success = False

                log_block("OWNER SAVE DEBUG")
                log_line("TYPE", draft.get("type"))
                log_line("NAME", draft.get("name"))
                log_line("PHONE", draft.get("phone"))
                log_line("CITY", draft.get("city"))
                log_line("STATE", draft.get("state"))
                log_line("MAPS_LINK", draft.get("maps_link"))
                log_line("PHOTO_FILE_ID", draft.get("photo_file_id"))
                log_line("UID", uid)
                log_line("DISTANCE_WARNING", draft.get("distance_warning"))
                log_line("DUPLICATE_MESSAGE", draft.get("duplicate_message"))

                try:
                    if ENABLE_SHEETS:

                        # ADMIN → write directly to OWNERS_MASTER
                        if str(uid) in [str(a) for a in ADMIN_IDS]:

                            owner_id = await run_sheet(
                                context,
                                create_owner_direct,
                                uid,
                                draft.get("coords",""),
                                draft.get("maps_link",""),
                                draft.get("photo_file_id",""),
                                draft.get("name",""),
                                draft.get("phone",""),
                                draft.get("email",""),
                                draft.get("socials",""),
                                f"{draft.get('city','')}, {draft.get('state','')}".strip(", "),
                                draft.get("source_platform",""),
                                draft.get("source_link","")
                            )

                            submission_id = None

                        # WORKER → send to submission queue
                        else:

                            submission_id = await run_sheet(
                                context,
                                create_owner_submission,
                                uid,
                                draft.get("coords",""),
                                draft.get("maps_link",""),
                                draft.get("photo_file_id",""),
                                draft.get("name",""),
                                draft.get("phone",""),
                                draft.get("email",""),
                                draft.get("socials",""),
                                f"{draft.get('city','')}, {draft.get('state','')}".strip(", "),
                                draft.get("source_platform",""),
                                draft.get("source_link",""),
                                draft.get("distance_warning","")
                            )
                    else:
                        print("TEST MODE — OWNER WOULD BE SAVED:", draft)

                    save_success = True

                except Exception as e:
                    log_block("OWNER SAVE ERROR")
                    log_line("ERROR", repr(e))
                    log_line("DRAFT DATA", draft)
                    unlock_user(context, ACCOUNT_CONFIRM)

                if save_success:

                    # ===== NOTIFY ADMINS ABOUT NEW PENDING ACCOUNT =====
                    try:

                        if submission_id and ADMIN_IDS:

                            for admin in ADMIN_IDS:

                                await context.bot.send_message(
                                    chat_id=admin,
                                    text="🔴 New Pending Account"
                                )

                    except Exception as e:
                        log_block("ADMIN NOTIFY ERROR")
                        log_line("ERROR", repr(e))

                    if str(uid) in [str(a) for a in ADMIN_IDS]:
                        message = "✅ Account created successfully."
                    else:
                        message = "⏳ Account submitted. Waiting for admin approval."

                    unlock_user(context, ACCOUNT_NONE)

                    await update.message.reply_text(
                        message,
                        reply_markup=base_nav_keyboard()
                    )

                    clear_user_session(context)
                    await open_menu_for_role(update, context, role)
                    return
                else:
                    await update.message.reply_text(
                        "❌ Error saving account. Please try again.",
                        reply_markup=confirm_keyboard()
                    )
                    return

        # ================= EDIT SELECT =================
        if state == ACCOUNT_EDIT_SELECT:

            if text == "Name":
                context.user_data["account_state"] = ACCOUNT_EDIT_NAME
                await update.message.reply_text(
                    "Enter new name:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "Phone":
                context.user_data["account_state"] = ACCOUNT_EDIT_PHONE
                await update.message.reply_text(
                    "Enter new phone:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "City":
                context.user_data["account_state"] = ACCOUNT_EDIT_CITY
                await update.message.reply_text(
                    "Enter new city:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "State":
                context.user_data["account_state"] = ACCOUNT_EDIT_STATE
                await update.message.reply_text(
                    "Enter new state:",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 BACK")]], resize_keyboard=True)
                )
                return

            if text == "Location":
                context.user_data["account_state"] = ACCOUNT_LOCATION
                keyboard = ReplyKeyboardMarkup(
                    [[KeyboardButton("📍 SEND LOCATION", request_location=True)],
                     [KeyboardButton("🔙 BACK")]],
                    resize_keyboard=True
                )
                await update.message.reply_text("Send new location:", reply_markup=keyboard)
                return

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_CONFIRM
                draft = context.user_data["account_draft"]

                await update.message.reply_text(
                    f"Review account:\n"
                    f"Type: {draft.get('type','')}\n"
                    f"Name: {draft.get('name','')}\n"
                    f"Phone: {draft.get('phone','')}\n"
                    f"City/State: {draft.get('city','') + ', ' if draft.get('city') else ''}{draft.get('state','')}",
                    reply_markup=confirm_keyboard()
                )
                return

            return


        # ================= APPLY EDIT =================
        if state in [ACCOUNT_EDIT_NAME, ACCOUNT_EDIT_PHONE, ACCOUNT_EDIT_CITY, ACCOUNT_EDIT_STATE]:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_EDIT_SELECT
                await update.message.reply_text(
                    "Select field to edit:",
                    reply_markup=edit_menu_keyboard()
                )
                return

            if state == ACCOUNT_EDIT_NAME:
                context.user_data.setdefault("account_draft", {})["name"] = text

            elif state == ACCOUNT_EDIT_PHONE:
                context.user_data["account_draft"]["phone"] = text

            elif state == ACCOUNT_EDIT_CITY:
                context.user_data["account_draft"]["city"] = text

            elif state == ACCOUNT_EDIT_STATE:
                context.user_data["account_draft"]["state"] = text

            context.user_data["account_state"] = ACCOUNT_CONFIRM
            draft = context.user_data["account_draft"]

            await update.message.reply_text(
                f"Review account:\n"
                f"Type: {draft.get('type','')}\n"
                f"Name: {draft.get('name','')}\n"
                f"Phone: {draft.get('phone','')}\n"
                f"City/State: {draft.get('city','') + ', ' if draft.get('city') else ''}{draft.get('state','')}",
                reply_markup=confirm_keyboard()
            )
            return

        # ================= LOCATION CAPTURE =================
        if state == ACCOUNT_LOCATION:

            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_CONFIRM
                await update.message.reply_text(
                    "Back to review:",
                    reply_markup=confirm_keyboard()
                )
                return

            if update.message.location:
                loc = update.message.location
                draft = context.user_data.setdefault("account_draft", {})

                maps_link = f"https://maps.google.com/?q={loc.latitude},{loc.longitude}"

                log_block("LOCATION RECEIVED")
                log_line("LAT", loc.latitude)
                log_line("LON", loc.longitude)
                log_line("MAPS_LINK", maps_link)

                draft["maps_link"] = maps_link
                draft["coords"] = f"{loc.latitude},{loc.longitude}"
                draft["lat"] = loc.latitude
                draft["lon"] = loc.longitude

                # ===== CHECK FOR NEARBY YARDS =====
                try:

                    # prevent duplicate check from running twice
                    if draft.get("duplicate_checked"):
                        nearby = []
                    else:
                        draft["duplicate_checked"] = True

                        nearby = await run_sheet(
                            context,
                            check_nearby_accounts,
                            loc.latitude,
                            loc.longitude
                        )

                    log_block("NEARBY SEARCH RESULT")
                    log_line("NEARBY_ROWS", nearby)

                    if nearby:
                        log_line("NEARBY_COUNT", len(nearby))
                        log_line("FIRST_NEARBY_ROW", nearby[0])
                    else:
                        log_line("NEARBY_STATUS", "NO_NEARBY_RESULTS")

                    if nearby:

                        nearby.sort(key=lambda x: x[1])

                        nearest = nearby[0]
                        owner_row, dist = nearest

                        warning = f"WITHIN_{int(dist)}M_OF_{owner_row[0]}"
                        draft["distance_warning"] = warning

                        log_block("NEARBY OWNER DETECTED")
                        log_line("DISTANCE_METERS", int(dist))
                        log_line("OWNER_ID", owner_row[0])

                        draft["duplicate_message"] = (
                            f"⚠ Possible duplicate yard\n"
                            f"Distance: {int(dist)} meters\n"
                            f"Owner ID: {owner_row[0]}"
                        )

                        try:
                            log_block("DUPLICATE PHOTO DEBUG")
                            log_line("OWNER_ROW", owner_row)
                            log_line("ROW_LENGTH", len(owner_row))

                            existing_photo = None

                            if len(owner_row) >= 11:
                                existing_photo = owner_row[10]

                            log_line("EXISTING_PHOTO_CELL", existing_photo)

                            await update.message.reply_text(
                                "⚠ Possible duplicate yard detected.\n"
                                f"Distance: {int(dist)} meters\n"
                                f"Owner ID: {owner_row[0]}"
                            )

                            if existing_photo:

                                draft["existing_photo"] = existing_photo

                                await update.message.reply_photo(
                                    photo=existing_photo,
                                    caption="Existing yard photo for comparison"
                                )

                            else:
                                await update.message.reply_text(
                                    "⚠ Existing yard photo not found."
                                )

                            draft["duplicate_pending"] = True

                            await update.message.reply_text(
                                "⚠ Possible duplicate yard detected.\n"
                                "Compare the location with the saved yard photo.\n\n"
                                "Continue anyway?",
                                reply_markup=ReplyKeyboardMarkup(
                                    [
                                        [KeyboardButton("➡ CONTINUE")],
                                        [KeyboardButton("❌ CANCEL")]
                                    ],
                                    resize_keyboard=True
                                )
                            )

                            context.user_data["account_state"] = ACCOUNT_PHOTO
                            return

                        except Exception as e:
                            log_block("EXISTING PHOTO ERROR")
                            log_line("ERROR", repr(e))
                except Exception as e:
                    log_block("DISTANCE CHECK ERROR")
                    log_line("ERROR", repr(e))

                context.user_data["account_state"] = ACCOUNT_PHOTO

                if not draft.get("photo_prompt_sent"):

                    draft["photo_prompt_sent"] = True

                    await update.message.reply_text(
                        "📸 Now send a yard photo:",
                        reply_markup=ReplyKeyboardMarkup(
                            [[KeyboardButton("🔙 BACK")]],
                            resize_keyboard=True
                        )
                    )
                return

            else:
                await update.message.reply_text(
                    "Please send the location using the button."
                )
                return

        # ================= PHOTO CAPTURE =================
        if state == ACCOUNT_PHOTO:

            # ---- CONTINUE ----
            if btn == "CONTINUE":

                draft = context.user_data.setdefault("account_draft", {})

                # if duplicate warning exists → go to duplicate confirmation
                if draft.get("duplicate_pending") and not draft.get("duplicate_confirmed"):
                    context.user_data["account_state"] = ACCOUNT_DUPLICATE_CHECK
                    await update.message.reply_text(
                        "Possible duplicate yard detected.\nContinue anyway?",
                        reply_markup=ReplyKeyboardMarkup(
                            [
                                [KeyboardButton("➡ CONTINUE")],
                                [KeyboardButton("❌ CANCEL")]
                            ],
                            resize_keyboard=True
                        )
                    )
                    return

                context.user_data["account_state"] = ACCOUNT_OWNER_NAME

                await update.message.reply_text(
                    "Enter owner name:",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("🔙 BACK")]],
                        resize_keyboard=True
                    )
                )
                return


            # ---- CANCEL ----
            if btn == "CANCEL":

                clear_user_session(context)
                await open_menu_for_role(update, context, role)
                return


            if text == "🔙 BACK":
                context.user_data["account_state"] = ACCOUNT_LOCATION
                keyboard = ReplyKeyboardMarkup(
                    [[KeyboardButton("📍 SEND LOCATION", request_location=True)],
                     [KeyboardButton("🔙 BACK")]],
                    resize_keyboard=True
                )
                await update.message.reply_text(
                    "Send location again:",
                    reply_markup=keyboard
                )
                return

            if update.message.photo:
                draft = context.user_data.setdefault("account_draft", {})

                photo = update.message.photo[-1]
                draft["photo_file_id"] = photo.file_id

                log_block("PHOTO RECEIVED")
                log_line("FILE_ID", photo.file_id)

                file = await context.bot.get_file(photo.file_id)
                draft["photo_url"] = file.file_path

                log_line("FILE_PATH", draft["photo_url"])

                if draft.get("duplicate_confirmed"):

                    if not draft.get("name"):
                        context.user_data["account_state"] = ACCOUNT_OWNER_NAME

                        await update.message.reply_text(
                            "Enter owner name:",
                            reply_markup=ReplyKeyboardMarkup(
                                [[KeyboardButton("🔙 BACK")]],
                                resize_keyboard=True
                            )
                        )
                    else:
                        context.user_data["account_state"] = ACCOUNT_CONFIRM

                        draft = context.user_data["account_draft"]

                        await update.message.reply_text(
                            f"Review account:\n"
                            f"Type: {draft.get('type','')}\n"
                            f"Name: {draft.get('name','')}\n"
                            f"Phone: {draft.get('phone','')}\n"
                            f"City/State: {draft.get('city','') + ', ' if draft.get('city') else ''}{draft.get('state','')}",
                            reply_markup=confirm_keyboard()
                        )
                    return

                #if draft.get("distance_warning"):
                    #context.user_data["account_state"] = ACCOUNT_DUPLICATE_CHECK

                if draft.get("distance_warning"):

                    keyboard = ReplyKeyboardMarkup(
                        [
                            [KeyboardButton("➡ CONTINUE")],
                            [KeyboardButton("❌ CANCEL")]
                        ],
                        resize_keyboard=True
                    )

                    message = "Location captured ✅\nPhoto captured ✅\n\n"

                    if draft.get("duplicate_message"):
                        message += draft["duplicate_message"] + "\n\nContinue anyway?"
                    else:
                        message += "Continue to owner details?"

                    await update.message.reply_text(
                        message,
                        reply_markup=keyboard
                    )

                else:

                    keyboard = ReplyKeyboardMarkup(
                        [
                            [KeyboardButton("➡ CONTINUE")],
                            [KeyboardButton("❌ CANCEL")]
                        ],
                        resize_keyboard=True
                    )

                    await update.message.reply_text(
                        "Location and photo captured.\n\n"
                        "Continue to owner details?",
                        reply_markup=keyboard
                    )

                return

            return

        # ================= DUPLICATE CHECK =================
        if state == ACCOUNT_DUPLICATE_CHECK:

            if btn == "CANCEL":
                clear_user_session(context)
                await open_menu_for_role(update, context, role)
                return

            if btn != "CONTINUE":
                return

            draft = context.user_data.setdefault("account_draft", {})
            draft["duplicate_confirmed"] = True
            draft["duplicate_pending"] = False

            # if photo not yet sent → ask for photo
            if not draft.get("photo_file_id"):

                context.user_data["account_state"] = ACCOUNT_PHOTO

                await update.message.reply_text(
                    "📸 Now send a yard photo:",
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("🔙 BACK")]],
                        resize_keyboard=True
                    )
                )
                return

            # photo already exists → move forward
            context.user_data["account_state"] = ACCOUNT_OWNER_NAME

            await update.message.reply_text(
                "Enter owner name:",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("🔙 BACK")]],
                    resize_keyboard=True
                )
            )
            return

    # ================= GLOBAL BACK BUTTON =================
    if text == PANEL_BACK:
        if update.message and update.message.text:
            await open_menu_for_role(update, context, role)
        return
    # ================= ITEMS WIZARD GUARD =================
    if context.user_data.get("item_state"):

        handled = await handle_items_panel(update, context, text, role, status)

        if handled:
            return

    # ================= ITEMS PANEL =================
    handled = await handle_items_panel(update, context, text, role, status)

    if handled:
        return

    # ================= ACCOUNTS (ADMIN + WORKERS) =================
    if text == PANEL_ACCOUNTS and status == "ACTIVE":

        await update.message.reply_text(
            "Accounts Menu",
            reply_markup=accounts_menu(role)
        )
        return

    # ================= ADD ACCOUNT =================
    if text == "➕ ADD ACCOUNT" and status == "ACTIVE":

        context.user_data["account_state"] = ACCOUNT_TYPE
        context.user_data["account_draft"] = {
            "email": "",
            "city": "",
            "state": "",
            "source_platform": "",
            "source_link": "",
            "distance_warning": "",
            "coords": "",
            "maps_link": "",
            "photo_url": ""
        }

        keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("📍 LOCATION")],
                [KeyboardButton("🌐 ONLINE")],
                [KeyboardButton("🏛️ AUCTION")],
                [KeyboardButton("🔙 BACK")]
            ],
            resize_keyboard=True
        )

        await update.message.reply_text(
            "Select account type:",
            reply_markup=keyboard,
        )
        return

    # ================= MY ACCOUNTS =================
    if text == "👤 MY ACCOUNTS" and status == "ACTIVE":

        await update.message.reply_text(
            "📋 Your accounts will appear here (Google Sheets integration coming next)."
        )
        return


    # ================= NEARBY ACCOUNTS =================
    if text == "📍 NEARBY ACCOUNTS" and status == "ACTIVE":

        await update.message.reply_text(
            "📍 Nearby accounts feature coming soon."
        )
        return


    # ================= SEARCH ACCOUNT =================
    if text == "🔎 SEARCH ACCOUNT" and status == "ACTIVE":

        await update.message.reply_text(
            "🔎 Send a name or phone number to search accounts (feature coming next)."
        )
        return
        
    # ================= ADMIN PANEL NAVIGATION =================
    if role == "ADMIN":
        if "PENDING ACCOUNTS" in btn:

            try:
                rows = await run_sheet(
                    context,
                    get_pending_owner_submissions
                )

                log_block("PENDING LOAD DEBUG")

                try:
                    for r in rows:
                        log_line("ROW_STATUS", r[13] if len(r) > 13 else "NO_STATUS")
                except Exception as e:
                    log_line("STATUS_PARSE_ERROR", repr(e))

                log_block("PENDING ACCOUNTS LOAD")

                if not rows:
                    rows = []

                log_line("ROWS_RETURNED", len(rows))

                try:
                    ids = [str(r[0]) for r in rows]
                    log_line("SUBMISSION_IDS", ", ".join(ids) if ids else "NONE")
                except Exception as e:
                    log_line("ID_PARSE_ERROR", repr(e))

                if not rows:
                    await update.message.reply_text("No pending owner submissions.")
                    return

                await update.message.reply_text(
                    "📋 Pending Account Submissions"
                )

                for r in rows:

                    submission_id = r[0]

                    # skip submissions already reviewed in this session
                    if POSTPONED_OWNER_SUBMISSIONS.get(submission_id) == "REVIEWED":
                        log_line("SKIP_ALREADY_REVIEWED", submission_id)
                        continue

                    worker_id = r[1]

                    coords = r[3]
                    maps_link = r[4]
                    photo = r[5]

                    name = r[6]
                    phone = r[7]
                    email = r[8]
                    socials = r[9]
                    city = r[10]

                    distance_warning = r[15] if len(r) > 15 else ""

                    log_block("ADMIN DUPLICATE CHECK")
                    log_line("ROW_LENGTH", len(r))
                    log_line("RAW_DISTANCE_WARNING", distance_warning)

                    duplicate_message = ""
                    owner_id = ""

                    if distance_warning:

                        parts = distance_warning.split("_OF_")

                        if len(parts) == 2:
                            meters = parts[0].replace("WITHIN_", "").replace("M", "")
                            owner_id = parts[1]

                            duplicate_message = (
                                f"\n⚠ Possible duplicate yard detected"
                                f"\nDistance: {meters} meters"
                                f"\nOwner ID: {owner_id}"
                            )

                        else:
                            duplicate_message = f"\n⚠ Possible duplicate\n{distance_warning}"

                        log_line("ADMIN_WARNING_DISPLAYED", duplicate_message)
                    else:
                        log_line("ADMIN_WARNING_DISPLAYED", "NONE")

                    caption = (
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "📥 SUBMISSION REVIEW\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        f"Submission ID: {submission_id}\n"
                        f"👤 Name: {name}\n"
                        f"📞 Phone: {phone}\n"
                        f"📧 Email: {email}\n"
                        f"🌐 Socials: {socials}\n"
                        f"📍 City: {city}\n"
                        f"🗺 Maps: {maps_link}\n"
                        f"🆔 Finder ID: {worker_id}"
                        f"{duplicate_message}\n\n"
                        "Next messages below:\n"
                        "1) submitted photo\n"
                        "2) existing photo (if duplicate)\n"
                        "3) map pin"
                    )

                    keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ APPROVE", callback_data=f"OWNER_APPROVE|{submission_id}|{worker_id}"),
                            InlineKeyboardButton("❌ REJECT", callback_data=f"OWNER_REJECT|{submission_id}|{worker_id}")
                        ]
                    ])

                    media = []

                    if photo:
                        media.append(
                            InputMediaPhoto(
                                media=photo
                            )
                        )

                    existing_photo = None
                    existing_map = ""

                    if distance_warning and owner_id:

                        try:
                            from sheets_logger import get_owner_by_id

                            owner_row = await run_sheet(
                                context,
                                get_owner_by_id,
                                owner_id
                            )

                            if owner_row and len(owner_row) >= 11:
                                existing_photo = owner_row[10]

                            if owner_row and len(owner_row) >= 10:
                                existing_map = owner_row[9]

                        except Exception as e:
                            log_line("OWNER_LOOKUP_ERROR", repr(e))

                    if existing_photo:

                        media.append(
                            InputMediaPhoto(
                                media=existing_photo
                            )
                        )

                    if media:

                        messages = await context.bot.send_media_group(
                            chat_id=update.effective_chat.id,
                            media=media
                        )

                        media_ids = [m.message_id for m in messages]

                        main_msg = await update.message.reply_text(
                            caption + f"\n\n🆕 Submitted Map:\n{maps_link}\n\n📍 Existing Map:\n{existing_map}",
                            reply_markup=keyboard
                        )

                    else:

                        media_ids = []

                        main_msg = await update.message.reply_text(
                            caption + f"\n\n🆕 Submitted Map:\n{maps_link}\n\n📍 Existing Map:\n{existing_map}",
                            reply_markup=keyboard
                        )

                    POSTPONED_OWNER_SUBMISSIONS[submission_id] = {
                        "chat_id": update.effective_chat.id,
                        "main_msg": main_msg.message_id,
                        "media_msgs": media_ids
                    }

            except Exception as e:
                log_block("PENDING LOAD ERROR")
                log_line("ERROR", repr(e))

            return
        if text == PANEL_BACK and status == "ACTIVE":
            await open_menu_for_role(update, context, role)
            return

        if text == PANEL_ACCOUNTS:
            await update.message.reply_text(
                "Accounts Menu",
                reply_markup=accounts_menu(role)
            )
            return

        if text == PANEL_WORKFLOW:

            if not POSTPONED_OWNER_SUBMISSIONS:
                await update.message.reply_text("No postponed owner submissions.")
                return

            for sid, data in POSTPONED_OWNER_SUBMISSIONS.items():

                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ APPROVE", callback_data=f"OWNER_APPROVE|{sid}|0"),
                        InlineKeyboardButton("❌ REJECT", callback_data=f"OWNER_REJECT|{sid}|0")
                    ]
                ])

                await update.message.reply_text(
                    f"⏳ Postponed Submission\nSubmission ID: {sid}",
                    reply_markup=keyboard
                )

            return

        if text == PANEL_USERS:
            await update.message.reply_text("👥 USERS panel opened")
            return

        if text == PANEL_TASKS:
            await update.message.reply_text("📝 TASKS panel opened")
            return

        if text == PANEL_REPORTS:
            await update.message.reply_text("📊 REPORTS panel opened")
            return

        if text == PANEL_SYSTEM:
            await update.message.reply_text("⚙️ SYSTEM panel opened")
            return

    query = update.callback_query
    if not query:
        return

    data = query.data or ""

    # owner approval system
    if data.startswith("OWNER_"):
        from accounts import owner_review_callback
        await owner_review_callback(update, context)
        return

    # user approval system
    if data.startswith("APPROVE") or data.startswith("REJECT"):
        from users import assign_role
        parts = data.split("|")

        if parts[0] == "APPROVE":
            telegram_id = parts[1]
            role = parts[2]

            assign_role(telegram_id, role, str(query.from_user.id))

            await query.edit_message_text(
                f"✅ User approved\nID: {telegram_id}\nRole: {role}"
            )

        elif parts[0] == "REJECT":

            await query.edit_message_text(
                f"❌ User rejected\nID: {parts[1]}"
            )

from accounts import owner_review_callback

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data.startswith("OWNER_"):
        await owner_review_callback(update, context)
        return

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    # OWNER submission review
    if data.startswith("OWNER_"):
        await owner_review_callback(update, context)
        return