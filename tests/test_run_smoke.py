from pathlib import Path

import polars as pl

import run as run_module


def test_pipeline_writes_chain(tmp_path, monkeypatch):
    monkeypatch.setattr(run_module.config, "OUT_DIR", tmp_path)
    monkeypatch.setattr(run_module.stage1, "pull_prozorro",
        lambda **k: [{"contractID": "c1", "id": "c1",
            "suppliers": [{"name": "ТОВ \"Шлях\"", "identifier": {"id": "31725604"}}],
            "value": {"amount": 1000000},
            "items": [{"classification": {"id": "45233140-2"},
                       "deliveryAddress": {"region": "Київ"}}]}])
    monkeypatch.setattr(run_module.stage1, "pull_spending",
        lambda **k: [{"id": "tx1", "recipt_edrpou": "31725604",
            "recipt_name": "ТОВ \"Шлях\"", "amount": 750000,
            "trans_date": "2025-10-15", "payment_details": "ремонт"}])
    monkeypatch.setattr(run_module.stage1, "pull_ted",
        lambda **k: [{"publication-number": "t1", "classification-cpv": ["45233140"],
            "organisation-name-tenderer": {"eng": ["Шлях"]},
            "organisation-country-tenderer": ["UKR"],
            "organisation-identifier-tenderer": ["31725604"],  # matches the contract supplier EDRPOU
            "total-value": 500000, "total-value-cur": "EUR",
            "place-of-performance": ["UA"]}])

    run_module.main(target=1, scan_cap=1)

    chain = pl.read_parquet(Path(tmp_path) / "chain.parquet")
    assert chain.to_dicts()[0]["state"] == "full"
    assert (Path(tmp_path) / "funnel.parquet").exists()


def test_pipeline_ted_nonfatal(tmp_path, monkeypatch):
    monkeypatch.setattr(run_module.config, "OUT_DIR", tmp_path)
    monkeypatch.setattr(run_module.stage1, "pull_prozorro",
        lambda **k: [{"contractID": "c1", "id": "c1",
            "suppliers": [{"name": "ТОВ \"Шлях\"", "identifier": {"id": "31725604"},
                           "address": {"region": "Київ"}}],
            "value": {"amount": 1000000},
            "items": [{"classification": {"id": "45233140-2"}}]}])
    monkeypatch.setattr(run_module.stage1, "pull_spending",
        lambda **k: [{"id": "tx1", "recipt_edrpou": "31725604",
            "recipt_name": "ТОВ \"Шлях\"", "amount": 750000,
            "trans_date": "2025-10-15", "payment_details": "ремонт"}])

    def _boom(**k):
        raise RuntimeError("TED 400")
    monkeypatch.setattr(run_module.stage1, "pull_ted", _boom)

    run_module.main(target=1, scan_cap=1)

    chain = pl.read_parquet(tmp_path / "chain.parquet")
    row = chain.to_dicts()[0]
    assert row["state"] == "payment_no_ted"
    assert row["ted_id"] is None
