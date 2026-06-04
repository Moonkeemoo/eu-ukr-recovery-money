import polars as pl

from recovery.stage4_chain import build_chain, build_funnel


def _joined():
    return pl.DataFrame([
        {"contract_id": "c1", "supplier_edrpou": "1", "supplier_name": "A",
         "cpv_div": "45", "region": "Київ", "contract_year": 2024,
         "contract_amount_uah": 1000000,
         "paid_amount_uah": 750000, "ted_id": "t1", "amount_eur": 500000,
         "ted_match_confidence": 1.0},
        {"contract_id": "c2", "supplier_edrpou": "2", "supplier_name": "B",
         "cpv_div": "45", "region": "Львів", "contract_year": 2024,
         "contract_amount_uah": 500000,
         "paid_amount_uah": 0, "ted_id": None, "amount_eur": None,
         "ted_match_confidence": None},
        {"contract_id": "c3", "supplier_edrpou": "3", "supplier_name": "C",
         "cpv_div": "71", "region": "Одеса", "contract_year": 2025,
         "contract_amount_uah": 200000,
         "paid_amount_uah": 200000, "ted_id": None, "amount_eur": None,
         "ted_match_confidence": None},
    ])


def test_build_chain_tags_state():
    chain = build_chain(_joined())
    state = {r["contract_id"]: r["state"] for r in chain.to_dicts()}
    assert state["c1"] == "full"
    assert state["c2"] == "contract_no_payment"
    assert state["c3"] == "payment_no_ted"


def test_build_chain_carries_contract_year():
    import polars as pl
    from recovery.stage4_chain import build_chain
    joined = pl.DataFrame({
        "contract_id": ["c1"], "supplier_edrpou": ["111"], "supplier_name": ["X"],
        "cpv_div": ["45"], "region": ["Київ"], "contract_year": [2024],
        "contract_amount_uah": [100.0], "paid_amount_uah": [50.0],
        "amount_eur": [None], "ted_id": [None], "ted_match_confidence": [None],
    })
    assert build_chain(joined).to_dicts()[0]["contract_year"] == 2024


def test_build_funnel_counts():
    funnel = build_funnel(_joined())
    counts = {r["step"]: r["count"] for r in funnel.to_dicts()}
    assert counts["contracts"] == 3
    assert counts["with_payment"] == 2
    assert counts["with_ted_overlay"] == 1
