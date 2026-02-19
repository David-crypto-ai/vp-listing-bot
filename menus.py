from telegram import ReplyKeyboardMarkup, KeyboardButton

BTN_START = "▶ START"

# Shared buttons
BTN_HELP = "❓ HELP"
BTN_NEW_TODO = "🆕 NEW TO DO"
BTN_COMPLETE_TASK = "✅ COMPLETE TASK"
BTN_MY_ACCOUNTS = "👤 MY ACCOUNTS"
BTN_FOLLOW_UP = "📞 FOLLOW UP CONTACT"
BTN_EDIT_ITEM = "🏷️ EDIT ITEM"

# Finder
BTN_NEW_ITEM = "📦 NEW ITEM"
BTN_ADD_OWNER = "👤 ADD OWNER"
BTN_MY_ITEMS = "🗂️ MY ITEMS"

# Seller
BTN_GET_PRICE = "💰 GET PRICE"
BTN_MARK_SOLD = "✅ MARK SOLD"
BTN_MY_SALES = "🗂️ MY SALES"

# Gatekeeper/Admin
BTN_APPROVE_PUBLISH_NEXT = "✅ APPROVE & PUBLISH NEXT"
BTN_REQUEST_CHANGES = "📝 REQUEST CHANGES"
BTN_HIDE_ITEM = "🙈 HIDE ITEM"
BTN_ASSIGN_SELLER = "🧑‍💼 ASSIGN SELLER"
BTN_VIEW_PENDING = "🗂️ VIEW PENDING"
BTN_REPORTS = "📊 REPORTS"

# Admin special
BTN_APPROVE_NEW_WORKER = "👤 APPROVE NEW WORKER"
BTN_ASSIGN_REMOVE_ROLES = "🧑‍💼 ASSIGN/REMOVE ROLES"

def kb(rows):
    return ReplyKeyboardMarkup(
        [[KeyboardButton(x) for x in row] for row in rows],
        resize_keyboard=True
    )

def start_keyboard():
    return kb([[BTN_START]])

def menu_for_role(role: str) -> ReplyKeyboardMarkup:
    role = (role or "").upper().strip()

    # FINDER menu
    if role == "FINDER":
        return kb([
            [BTN_NEW_ITEM, BTN_ADD_OWNER],
            [BTN_MY_ITEMS, BTN_EDIT_ITEM],
            [BTN_MY_ACCOUNTS, BTN_FOLLOW_UP],
            [BTN_NEW_TODO, BTN_COMPLETE_TASK],
            [BTN_HELP],
        ])

    # SELLER menu
    if role == "SELLER":
        return kb([
            [BTN_GET_PRICE, BTN_MARK_SOLD],
            [BTN_MY_SALES, BTN_EDIT_ITEM],
            [BTN_MY_ACCOUNTS, BTN_FOLLOW_UP],
            [BTN_NEW_TODO, BTN_COMPLETE_TASK],
            [BTN_HELP],
        ])

    # BOTH menu
    if role in ("FINDER+SELLER", "BOTH"):
        return kb([
            [BTN_NEW_ITEM, BTN_ADD_OWNER],
            [BTN_MY_ITEMS, BTN_GET_PRICE],
            [BTN_MARK_SOLD, BTN_EDIT_ITEM],
            [BTN_MY_ACCOUNTS, BTN_FOLLOW_UP],
            [BTN_NEW_TODO, BTN_COMPLETE_TASK],
            [BTN_HELP],
        ])

    # GATEKEEPER menu
    if role == "GATEKEEPER":
        return kb([
            [BTN_APPROVE_PUBLISH_NEXT],
            [BTN_REQUEST_CHANGES, BTN_EDIT_ITEM],
            [BTN_HIDE_ITEM, BTN_ASSIGN_SELLER],
            [BTN_VIEW_PENDING, BTN_REPORTS],
            [BTN_FOLLOW_UP],
            [BTN_NEW_TODO, BTN_COMPLETE_TASK],
            [BTN_HELP],
        ])

    # ADMIN menu
    if role == "ADMIN":
        return kb([
            [BTN_APPROVE_PUBLISH_NEXT],
            [BTN_APPROVE_NEW_WORKER, BTN_ASSIGN_REMOVE_ROLES],
            [BTN_ASSIGN_SELLER, BTN_EDIT_ITEM],
            [BTN_HIDE_ITEM, BTN_REPORTS],
            [BTN_FOLLOW_UP],
            [BTN_NEW_TODO, BTN_COMPLETE_TASK],
            [BTN_HELP],
        ])

    # Default: pending
    return kb([[BTN_HELP]])
