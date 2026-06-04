from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "cache"
OUT_DIR = ROOT / "data" / "out"

# Extended reconstruction CPV divisions (first 2 digits of the CPV code).
CPV_DIVISIONS = ("45", "71", "09", "31", "34")

# Snapshot window: how many months back from today to ingest.
WINDOW_MONTHS = 12

# Real-data ingest bounds (see docs/superpowers/specs/2026-06-03-real-data-ingest-design.md)
PROZORRO_TARGET = 500       # stop after this many in-scope contracts
PROZORRO_SCAN_CAP = 1500    # stop after scanning this many feed stubs
SPENDING_BATCH = 10         # recipient EDRPOUs per request (API rejects >10: "Перевищено максимальний розмір масиву recipt_edrpous")
SPENDING_WINDOW_DAYS = 90   # spending date window (API hard limit is 92)

# API hosts (all unauthenticated for reading).
PROZORRO_OCDS = "https://public-api.prozorro.gov.ua/api/2.5"
SPENDING_API = "https://api.spending.gov.ua/api"
TED_SEARCH = "https://api.ted.europa.eu/v3/notices/search"

# TED v3 expert-search requires a non-empty `fields` list of valid field names.
# These are the only names normalize_ted consumes. `winner-name`/`value` from
# earlier drafts do NOT exist (caused HTTP 400), and `winner-partname` comes back
# empty — the supplier name actually lives in `organisation-name-tenderer`, a
# {lang: [names]} dict index-aligned with `organisation-country-tenderer`.
TED_FIELDS = (
    "publication-number",
    "classification-cpv",
    "organisation-name-tenderer",
    "organisation-country-tenderer",
    "total-value",
    "total-value-cur",
    "place-of-performance",
)


def cpv_in_scope(cpv: str | None) -> bool:
    """True if a CPV code belongs to a reconstruction division."""
    if not cpv:
        return False
    return cpv[:2] in CPV_DIVISIONS
