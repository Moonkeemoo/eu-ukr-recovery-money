from pathlib import Path

import polars as pl
from fastapi.testclient import TestClient


def _seed(out_dir: Path):
    pl.DataFrame([
        {"contract_id": "c1", "supplier_edrpou": "1", "supplier_name": "A",
         "cpv_div": "45", "region": "Київ", "contract_amount_uah": 1000000,
         "paid_amount_uah": 750000, "ted_amount_eur": 500000, "ted_id": "t1",
         "ted_match_confidence": 1.0, "state": "full"},
    ]).write_parquet(out_dir / "chain.parquet")
    pl.DataFrame([{"step": "contracts", "count": 1}]).write_parquet(out_dir / "funnel.parquet")


def _client(tmp_path, monkeypatch):
    from recovery import config
    monkeypatch.setattr(config, "OUT_DIR", tmp_path)
    import importlib
    import api.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app)


def test_kpi_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/kpi")
    assert resp.status_code == 200
    assert resp.json()["paid_uah"] == 750000


def test_sankey_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/sankey?sector=45")
    assert resp.status_code == 200
    assert "links" in resp.json()


def test_supplier_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/supplier/1")
    assert resp.json()["contracts"][0]["contract_id"] == "c1"


def test_gaps_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/gaps?type=contract_no_payment")
    assert resp.status_code == 200
    assert resp.json() == []  # seed row is state="full", so no gaps


def test_funnel_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/funnel")
    assert resp.status_code == 200
    assert resp.json()[0]["step"] == "contracts"
