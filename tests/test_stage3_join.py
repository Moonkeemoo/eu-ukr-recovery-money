import polars as pl

from recovery.stage3_join import join_core, attach_ted_overlay


def test_join_core_matches_on_edrpou():
    contracts = pl.DataFrame([
        {"contract_id": "c1", "supplier_edrpou": "31725604",
         "supplier_name_norm": "шлях", "cpv_div": "45", "amount_uah": 1000000, "region": "Київ"},
        {"contract_id": "c2", "supplier_edrpou": "99999999",
         "supplier_name_norm": "ніхто", "cpv_div": "45", "amount_uah": 500000, "region": "Львів"},
    ])
    spending = pl.DataFrame([
        {"recipient_edrpou": "31725604", "amount_uah": 600000},
        {"recipient_edrpou": "31725604", "amount_uah": 150000},
    ])
    joined = join_core(contracts, spending)
    by_id = {r["contract_id"]: r for r in joined.to_dicts()}
    assert by_id["c1"]["paid_amount_uah"] == 750000   # 600k + 150k aggregated
    assert by_id["c2"]["paid_amount_uah"] == 0        # no payment


def test_attach_ted_overlay():
    joined = pl.DataFrame([
        {"contract_id": "c1", "supplier_name_norm": "шлях", "cpv_div": "45"},
        {"contract_id": "c2", "supplier_name_norm": "нема", "cpv_div": "45"},
    ])
    ted = pl.DataFrame([
        {"ted_id": "t1", "winner_name_norm": "шлях", "cpv_div": "45", "amount_eur": 500000},
        {"ted_id": "t2", "winner_name_norm": "інша", "cpv_div": "45", "amount_eur": 100000},
    ])
    out = attach_ted_overlay(joined, ted)
    by_id = {r["contract_id"]: r for r in out.to_dicts()}

    row1 = by_id["c1"]
    assert row1["ted_id"] == "t1"
    assert row1["ted_match_confidence"] == 1.0

    row2 = by_id["c2"]
    assert row2["ted_match_confidence"] is None
    assert row2["ted_id"] is None


def test_ted_overlay_ignores_empty_names():
    joined = pl.DataFrame([
        {"contract_id": "c1", "supplier_name_norm": "", "cpv_div": "45"},
    ])
    ted = pl.DataFrame([
        {"ted_id": "t1", "winner_name_norm": "", "cpv_div": "45", "amount_eur": 500000},
    ])
    out = attach_ted_overlay(joined, ted)
    row = out.to_dicts()[0]
    assert row["ted_id"] is None
    assert row["ted_match_confidence"] is None
