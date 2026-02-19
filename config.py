import os

def _must(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v

TELEGRAM_TOKEN = _must("TELEGRAM_TOKEN")
SPREADSHEET_ID = _must("SPREADSHEET_ID")
GOOGLE_CREDENTIALS = _must("GOOGLE_CREDENTIALS")

ADMIN_IDS = set("6310898007")
for part in os.environ.get("ADMIN_IDS", "").split(","):
    part = part.strip()
    if part.isdigit():
        ADMIN_IDS.add(str(part))

# Worksheet/tab names
WORKSHEET_ITEMS = os.environ.get("WORKSHEET_ITEMS", "ITEMS_MASTER")
WORKSHEET_OWNERS = os.environ.get("WORKSHEET_OWNERS", "OWNERS_MASTER")
WORKSHEET_USERS = os.environ.get("WORKSHEET_USERS", "USERS_ROLES")
WORKSHEET_LOG = os.environ.get("WORKSHEET_LOG", "ACTIVITY_LOG")
WORKSHEET_TASKS = os.environ.get("WORKSHEET_TASKS", "TASKS_TODOS")

# Business rules
DAYS_CONFIRM_WINDOW = 30
DAYS_AUTO_HIDE = 40

# Reminders
TASK_REMINDER_FREQUENCY_MIN = 60
TASK_POLL_SECONDS = 60
STALE_CHECK_SECONDS = 3600
