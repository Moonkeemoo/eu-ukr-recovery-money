from pathlib import Path

import polars as pl

from recovery.queries import sankey, kpi, supplier, gaps, funnel


def _seed(out_dir: Path):
    pl.DataFrame([
        {"contract_id": "c1", "supplier_edrpou": "1", "supplier_name": "A",
         "cpv_div": "45", "region": "Київ", "contract_amount_uah": 1000000,
         "paid_amount_uah": 750000, "ted_amount_eur": 500000, "ted_id": "t1",
         "ted_match_confidence": 1.0, "state": "full"},
        {"contract_id": "c2", "supplier_edrpou": "2", "supplier_name": "B",
         "cpv_div": "71", "region": "Львів", "contract_amount_uah": 500000,
         "paid_amount_uah": 0, "ted_amount_eur": None, "ted_id": None,
         "ted_match_confidence": None, "state": "contract_no_payment"},
    ]).write_parquet(out_dir / "chain.parquet")
    pl.DataFrame([{"step": "contracts", "count": 2}]).write_parquet(out_dir / "funnel.parquet")


def test_kpi_totals(tmp_path):
    _seed(tmp_path)
    k = kpi(tmp_path)
    assert k["contracted_uah"] == 1500000
    assert k["paid_uah"] == 750000
    assert k["breaks"] == 1


def test_kpi_filtered_by_sector(tmp_path):
    _seed(tmp_path)
    k = kpi(tmp_path, sector="45")
    assert k["contracted_uah"] == 1000000
    assert k["breaks"] == 0


def test_sankey_has_nodes_and_links(tmp_path):
    _seed(tmp_path)
    s = sankey(tmp_path)
    assert {"nodes", "links"} <= set(s)
    assert len(s["nodes"]) >= 2


def test_supplier_detail(tmp_path):
    _seed(tmp_path)
    detail = supplier(tmp_path, "1")
    assert detail["contracts"][0]["contract_id"] == "c1"


def test_gaps_lists_breaks(tmp_path):
    _seed(tmp_path)
    rows = gaps(tmp_path, gap_type="contract_no_payment")
    assert len(rows) == 1
    assert rows[0]["contract_id"] == "c2"


def test_funnel_passthrough(tmp_path):
    _seed(tmp_path)
    assert funnel(tmp_path)[0]["step"] == "contracts"


def test_kpi_empty_sector_no_crash(tmp_path):
    _seed(tmp_path)
    k = kpi(tmp_path, sector="99")  # no rows match
    assert k["contracted_uah"] == 0
    assert k["paid_uah"] == 0
    assert k["breaks"] == 0


def test_gaps_empty_returns_list(tmp_path):
    _seed(tmp_path)
    assert gaps(tmp_path, gap_type="nonexistent_state") == []


def test_regions_distinct_sorted(tmp_path):
    _seed(tmp_path)
    from recovery.queries import regions
    assert regions(tmp_path) == ["Київ", "Львів"]


def test_breakdown_per_state(tmp_path):
    _seed(tmp_path)
    from recovery.queries import breakdown
    rows = {r["state"]: r for r in breakdown(tmp_path)}
    assert rows["full"]["count"] == 1
    assert rows["full"]["contracted_uah"] == 1000000
    assert rows["full"]["paid_uah"] == 750000
    assert rows["contract_no_payment"]["count"] == 1
    assert rows["contract_no_payment"]["paid_uah"] == 0


def test_breakdown_filtered(tmp_path):
    _seed(tmp_path)
    from recovery.queries import breakdown
    rows = breakdown(tmp_path, sector="45")
    assert len(rows) == 1
    assert rows[0]["state"] == "full"


def test_breakdown_empty_returns_list(tmp_path):
    _seed(tmp_path)
    from recovery.queries import breakdown
    assert breakdown(tmp_path, sector="99") == []
