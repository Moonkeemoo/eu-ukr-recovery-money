from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "cache"
OUT_DIR = ROOT / "data" / "out"

# Extended reconstruction CPV divisions (first 2 digits of the CPV code).
CPV_DIVISIONS = ("45", "71", "09", "31", "34")

# 12-month window, end is the snapshot date. Override END_DATE in tests.
WINDOW_MONTHS = 12

# API hosts (all unauthenticated for reading).
PROZORRO_OCDS = "https://public-api.prozorro.gov.ua/api/2.5"
SPENDING_API = "https://api.spending.gov.ua/api"
TED_SEARCH = "https://api.ted.europa.eu/v3/notices/search"


def cpv_in_scope(cpv: str | None) -> bool:
    """True if a CPV code belongs to a reconstruction division."""
    if not cpv:
        return False
    return cpv[:2] in CPV_DIVISIONS
