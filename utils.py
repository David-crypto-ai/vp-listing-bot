from datetime import datetime
from zoneinfo import ZoneInfo

# ======================================
# LOCAL TIME (Chihuahua, Mexico)
# ======================================
def now_str() -> str:
    return datetime.now(ZoneInfo("America/Chihuahua")).strftime("%Y-%m-%d %H:%M:%S")


def safe_text(x) -> str:
    return (x or "").strip()


def is_vin_17(v: str) -> bool:
    v = safe_text(v).upper()
    return len(v) == 17 and all(c.isalnum() for c in v)


def fmt_item_id(n: int) -> str:
    return f"VP-{n:06d}"
