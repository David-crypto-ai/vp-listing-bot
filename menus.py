from telegram import ReplyKeyboardMarkup, KeyboardButton

# ===== MAIN PANELS =====
PANEL_ITEMS = "📦 ITEMS"
PANEL_ACCOUNTS = "🏢 ACCOUNTS"
PANEL_WORKFLOW = "🔄 WORKFLOW"
PANEL_USERS = "👥 USERS"
PANEL_TASKS = "📝 TASKS"
PANEL_REPORTS = "📊 REPORTS PANEL"
PANEL_SYSTEM = "⚙️ SYSTEM"
PANEL_BACK = "🔙 BACK"

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

# Gatekeeper/Admin actions
BTN_APPROVE_PUBLISH_NEXT = "✅ APPROVE & PUBLISH NEXT"
BTN_REQUEST_CHANGES = "📝 REQUEST CHANGES"
BTN_HIDE_ITEM = "🙈 HIDE ITEM"
BTN_ASSIGN_SELLER = "🧑‍💼 ASSIGN SELLER"
BTN_VIEW_PENDING = "🗂️ VIEW PENDING"
BTN_REPORTS_ACTION = "📊 VIEW REPORTS"

# Admin special
BTN_APPROVE_NEW_WORKER = "👤 APPROVE NEW WORKER"
BTN_ASSIGN_REMOVE_ROLES = "🧑‍💼 ASSIGN/REMOVE ROLES"


# =============================
# Keyboard helper
# =============================
def kb(rows):
    return ReplyKeyboardMarkup(
        [[KeyboardButton(x) for x in row] for row in rows],
        resize_keyboard=True
    )

def start_keyboard():
    return kb([[BTN_START]])


# =============================
# ADMIN MAIN PANEL
# =============================
def admin_main_menu():
    return kb([
        [PANEL_ITEMS, PANEL_ACCOUNTS],
        [PANEL_WORKFLOW, PANEL_USERS],
        [PANEL_TASKS, PANEL_REPORTS],
        [PANEL_SYSTEM],
        [PANEL_BACK]
    ])


# =============================
# ROLE MENUS
# =============================
def menu_for_role(role: str) -> ReplyKeyboardMarkup:
    role = (role or "").upper().strip()

    # FINDER
    if role == "FINDER":
        return kb([
            [BTN_NEW_ITEM, BTN_ADD_OWNER],
            [BTN_MY_ITEMS, BTN_EDIT_ITEM],
            [BTN_MY_ACCOUNTS, BTN_FOLLOW_UP],
            [BTN_NEW_TODO, BTN_COMPLETE_TASK],
            [BTN_HELP],
        ])

    # SELLER
    if role == "SELLER":
        return kb([
            [BTN_GET_PRICE, BTN_MARK_SOLD],
            [BTN_MY_SALES, BTN_EDIT_ITEM],
            [BTN_MY_ACCOUNTS, BTN_FOLLOW_UP],
            [BTN_NEW_TODO, BTN_COMPLETE_TASK],
            [BTN_HELP],
        ])

    # BOTH
    if role in ("FINDER+SELLER", "BOTH"):
        return kb([
            [BTN_NEW_ITEM, BTN_ADD_OWNER],
            [BTN_MY_ITEMS, BTN_GET_PRICE],
            [BTN_MARK_SOLD, BTN_EDIT_ITEM],
            [BTN_MY_ACCOUNTS, BTN_FOLLOW_UP],
            [BTN_NEW_TODO, BTN_COMPLETE_TASK],
            [BTN_HELP],
        ])

    # GATEKEEPER
    if role == "GATEKEEPER":
        return kb([
            [BTN_APPROVE_PUBLISH_NEXT],
            [BTN_REQUEST_CHANGES, BTN_EDIT_ITEM],
            [BTN_HIDE_ITEM, BTN_ASSIGN_SELLER],
            [BTN_VIEW_PENDING, BTN_REPORTS_ACTION],
            [BTN_FOLLOW_UP],
            [BTN_NEW_TODO, BTN_COMPLETE_TASK],
            [BTN_HELP],
        ])

    # ADMIN (now opens control panel)
    if role == "ADMIN":
        return admin_main_menu()

    return kb([[BTN_HELP]])

# =========================================
# OPEN MENU FOR ROLE (called from main.py)
# =========================================
async def open_menu_for_role(update, context, role: str):
    keyboard = menu_for_role(role)

    await update.message.reply_text(
        f"Opened {role} menu",
        reply_markup=keyboard
    )
