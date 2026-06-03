import json
from pathlib import Path

from recovery.stage2_normalize import (
    normalize_prozorro, normalize_spending, normalize_ted,
)

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_normalize_prozorro():
    raw = _load("prozorro_page.json")["data"]
    df = normalize_prozorro(raw)
    row = df.to_dicts()[0]
    assert row["supplier_edrpou"] == "31725604"
    assert row["supplier_name_norm"] == "шлях"
    assert row["cpv_div"] == "45"
    assert row["amount_uah"] == 1000000
    assert row["region"] == "Київська область"
    assert row["redacted"] is False


def test_normalize_spending():
    raw = _load("spending_page.json")["items"]
    df = normalize_spending(raw)
    row = df.to_dicts()[0]
    assert row["recipient_edrpou"] == "31725604"
    assert row["recipient_name_norm"] == "шлях"
    assert row["amount_uah"] == 750000
    assert row["payment_date"] == "2025-10-15"


def test_normalize_ted():
    raw = _load("ted_page.json")["notices"]
    df = normalize_ted(raw)
    row = df.to_dicts()[0]
    assert row["ted_id"] == "00654321-2025"
    assert row["cpv_div"] == "45"
    assert row["winner_name_norm"] == "bud"
    assert row["amount_eur"] == 500000


def test_normalize_empty_input_keeps_schema():
    assert normalize_prozorro([]).columns == [
        "contract_id", "cpv", "cpv_div", "supplier_edrpou", "supplier_name",
        "supplier_name_norm", "amount_uah", "region", "redacted",
    ]
    assert normalize_spending([]).height == 0
    assert normalize_ted([]).height == 0
    assert "ted_id" in normalize_ted([]).columns
