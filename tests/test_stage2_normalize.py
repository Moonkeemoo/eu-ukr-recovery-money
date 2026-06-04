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
    rows = df.to_dicts()
    eur = rows[0]
    assert eur["ted_id"] == "00654321-2025"
    # Array-valued TED fields collapse to their first element (cpv -> division).
    assert eur["cpv"] == "45233140"
    assert eur["cpv_div"] == "45"
    assert eur["winner_name_norm"] == "bud"
    assert eur["region"] == "UA"
    # winner-country prefers the Ukrainian entry when a notice lists several winners.
    assert eur["winner_country"] == "UKR"
    assert eur["amount_eur"] == 500000

    # total-value is trusted as EUR only when total-value-cur says so (honest currency).
    pln = rows[1]
    assert pln["ted_id"] == "00777000-2025"
    assert pln["amount_eur"] is None


def test_normalize_empty_input_keeps_schema():
    assert normalize_prozorro([]).columns == [
        "contract_id", "cpv", "cpv_div", "supplier_edrpou", "supplier_name",
        "supplier_name_norm", "amount_uah", "region", "redacted", "contract_year",
    ]
    assert normalize_spending([]).height == 0
    assert normalize_ted([]).height == 0
    assert "ted_id" in normalize_ted([]).columns


def test_normalize_prozorro_parses_contract_year():
    raw = [{
        "contractID": "UA-1",
        "dateSigned": "2024-07-15T00:00:00+03:00",
        "items": [{"classification": {"id": "45233140-2"}}],
        "suppliers": [{"name": "ТОВ \"Шлях\"", "identifier": {"id": "31725604"}}],
        "value": {"amount": 100},
    }, {
        "contractID": "UA-2",  # no dateSigned -> null year
        "items": [{"classification": {"id": "45233140-2"}}],
        "suppliers": [{"name": "X", "identifier": {"id": "222"}}],
        "value": {"amount": 50},
    }]
    df = normalize_prozorro(raw)
    rows = df.to_dicts()
    assert rows[0]["contract_year"] == 2024
    assert rows[1]["contract_year"] is None


def test_normalize_prozorro_region_falls_back_to_supplier_address():
    raw = [{
        "contractID": "UA-9",
        "items": [{"classification": {"id": "45233140-2"}}],  # no deliveryAddress
        "suppliers": [{"name": "ТОВ \"Шлях\"", "identifier": {"id": "31725604"},
                       "address": {"region": "Полтавська область"}}],
        "value": {"amount": 1000},
    }]
    row = normalize_prozorro(raw).to_dicts()[0]
    assert row["region"] == "Полтавська область"
