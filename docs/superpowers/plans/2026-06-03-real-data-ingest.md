# Real-Data Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the ProZorro and spending ingest so `python run.py` pulls real reconstruction contracts and treasury payments from the live APIs (bounded to ~500 contracts), with TED made non-fatal.

**Architecture:** Only `stage1_ingest` (and small touches to `config`, `stage2_normalize`, `run.py`) change. ProZorro is walked newest-first via its `/contracts?descending=1` change-feed, fetching each `/contracts/{id}` and keeping in-scope-CPV records up to a target. Spending is pulled from `/v2/api/transactions/` with batched `recipt_edrpous` over quarterly (≤92-day) windows. Stages 2–4, queries, API and web are unchanged.

**Tech Stack:** Python 3.12, httpx (via existing `CachedClient`), polars; pytest + respx for tests.

---

## File Structure

```
src/recovery/config.py          # MODIFY: add PROZORRO_TARGET, PROZORRO_SCAN_CAP, SPENDING_BATCH, SPENDING_WINDOW_DAYS
src/recovery/stage1_ingest.py   # REWRITE pull_prozorro, pull_spending; add _quarter_windows helper; pull_ted unchanged
src/recovery/stage2_normalize.py# MODIFY normalize_prozorro: region fallback to supplier address
run.py                          # MODIFY: new pull signatures, TED non-fatal, --target/--scan-cap CLI
tests/test_stage1_ingest.py     # REWRITE to real API shapes (respx side_effect dispatchers)
tests/test_stage2_normalize.py  # ADD region-fallback test
tests/test_run_smoke.py         # ADD TED-non-fatal test
README.md                       # MODIFY: real-data ingest section
```

Real API shapes (confirmed by live probing 2026-06-03):
- ProZorro feed: `{"data":[{"id","dateModified"}], "next_page":{"offset","path"}}` (newest-first with `descending=1`).
- ProZorro contract: `{"data":{"contractID","items":[{"classification":{"scheme":"ДК021","id":"45233140-2"}}],"suppliers":[{"name","identifier":{"scheme":"UA-EDR","id":"31725604"},"address":{"region":"Київська область"}}],"value":{"amount":1000000}}}`.
- spending: bare JSON list of `{"id","trans_date","amount","recipt_edrpou","recipt_name","payment_details",...}`; query params `recipt_edrpous` (comma list), `startdate`/`enddate` (`YYYY-MM-DD`, ≤92 days).

---

### Task 1: config constants

**Files:**
- Modify: `src/recovery/config.py`
- Test: `tests/test_config_smoke.py`

- [ ] **Step 1: Add a failing test** (append to `tests/test_config_smoke.py`)

```python
def test_ingest_bounds_present():
    assert config.PROZORRO_TARGET == 500
    assert config.PROZORRO_SCAN_CAP == 1500
    assert config.SPENDING_BATCH == 20
    assert config.SPENDING_WINDOW_DAYS == 90
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_config_smoke.py::test_ingest_bounds_present -v`
Expected: FAIL (AttributeError).

- [ ] **Step 3: Add constants to `src/recovery/config.py`** (after `WINDOW_MONTHS = 12`)

```python
# Real-data ingest bounds (see docs/superpowers/specs/2026-06-03-real-data-ingest-design.md)
PROZORRO_TARGET = 500       # stop after this many in-scope contracts
PROZORRO_SCAN_CAP = 1500    # stop after scanning this many feed stubs
SPENDING_BATCH = 20         # recipient EDRPOUs per spending request
SPENDING_WINDOW_DAYS = 90   # spending date window (API hard limit is 92)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_config_smoke.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/recovery/config.py tests/test_config_smoke.py
git commit -m "feat: add real-data ingest bound constants to config"
```

---

### Task 2: rewrite `pull_prozorro`

**Files:**
- Modify: `src/recovery/stage1_ingest.py`
- Test: `tests/test_stage1_ingest.py`

- [ ] **Step 1: Replace the ProZorro test** in `tests/test_stage1_ingest.py`

Remove the existing `test_pull_prozorro_returns_records` and its `prozorro_page.json` usage; replace with a real-shape walk test. Add these imports at the top if absent: `import httpx`, `import respx`. New test:

```python
@respx.mock
def test_pull_prozorro_walks_feed_and_filters_cpv(tmp_path):
    feed_p1 = {"data": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
               "next_page": {"offset": "OFF2"}}
    feed_p2 = {"data": [], "next_page": {"offset": "OFF2"}}
    contracts = {
        "c1": {"data": {"contractID": "UA-1",
            "items": [{"classification": {"scheme": "ДК021", "id": "45233140-2"}}],
            "suppliers": [{"name": "A", "identifier": {"scheme": "UA-EDR", "id": "111"}}],
            "value": {"amount": 100}}},
        "c2": {"data": {"contractID": "UA-2",
            "items": [{"classification": {"scheme": "ДК021", "id": "15800000-6"}}],
            "suppliers": [{"name": "B", "identifier": {"id": "222"}}],
            "value": {"amount": 50}}},
        "c3": {"data": {"contractID": "UA-3",
            "items": [{"classification": {"scheme": "ДК021", "id": "71320000-7"}}],
            "suppliers": [{"name": "C", "identifier": {"id": "333"}}],
            "value": {"amount": 200}}},
    }

    def handler(request):
        path = request.url.path
        if path.endswith("/contracts"):
            offset = request.url.params.get("offset")
            return httpx.Response(200, json=(feed_p2 if offset else feed_p1))
        cid = path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=contracts[cid])

    respx.route(host="public-api.prozorro.gov.ua").mock(side_effect=handler)

    out = pull_prozorro(cache_dir=tmp_path, target=10, scan_cap=10)
    assert [c["contractID"] for c in out] == ["UA-1", "UA-3"]  # c2 (CPV 15) filtered out


@respx.mock
def test_pull_prozorro_stops_at_target(tmp_path):
    feed = {"data": [{"id": "c1"}, {"id": "c3"}], "next_page": {"offset": "OFF2"}}
    contracts = {
        "c1": {"data": {"contractID": "UA-1",
            "items": [{"classification": {"id": "45233140-2"}}],
            "suppliers": [{"name": "A", "identifier": {"id": "111"}}],
            "value": {"amount": 100}}},
        "c3": {"data": {"contractID": "UA-3",
            "items": [{"classification": {"id": "71320000-7"}}],
            "suppliers": [{"name": "C", "identifier": {"id": "333"}}],
            "value": {"amount": 200}}},
    }

    def handler(request):
        if request.url.path.endswith("/contracts"):
            return httpx.Response(200, json=feed)
        return httpx.Response(200, json=contracts[request.url.path.rsplit("/", 1)[-1]])

    respx.route(host="public-api.prozorro.gov.ua").mock(side_effect=handler)
    out = pull_prozorro(cache_dir=tmp_path, target=1, scan_cap=10)
    assert [c["contractID"] for c in out] == ["UA-1"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_stage1_ingest.py -k prozorro -v`
Expected: FAIL (current `pull_prozorro` uses `?page=` and `data["data"]` rows directly, no per-id fetch).

- [ ] **Step 3: Replace `pull_prozorro` in `src/recovery/stage1_ingest.py`** with:

```python
def pull_prozorro(cache_dir: Path, target: int = config.PROZORRO_TARGET,
                  scan_cap: int = config.PROZORRO_SCAN_CAP) -> list[dict]:
    """Walk the ProZorro contracts change-feed newest-first, fetch each full contract,
    and keep those with a reconstruction-CPV item. Stops at `target` kept or `scan_cap`
    scanned."""
    out: list[dict] = []
    scanned = 0
    offset = None
    with CachedClient(cache_dir / "prozorro") as client:
        while scanned < scan_cap and len(out) < target:
            params = {"descending": "1"}
            if offset:
                params["offset"] = offset
            feed = client.get_json(f"{config.PROZORRO_OCDS}/contracts", params=params)
            stubs = feed.get("data") or []
            if not stubs:
                break
            for stub in stubs:
                if scanned >= scan_cap or len(out) >= target:
                    break
                scanned += 1
                cid = stub.get("id")
                if not cid:
                    continue
                try:
                    rec = client.get_json(f"{config.PROZORRO_OCDS}/contracts/{cid}")
                except Exception:
                    continue  # skip a contract that fails to fetch; keep walking
                data = rec.get("data") or {}
                items = data.get("items") or []
                if any(config.cpv_in_scope((it.get("classification") or {}).get("id")) for it in items):
                    out.append(data)
            new_offset = (feed.get("next_page") or {}).get("offset")
            if not new_offset or new_offset == offset:
                break
            offset = new_offset
    print(f"ProZorro: scanned {scanned} contracts, kept {len(out)} in-scope")
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_stage1_ingest.py -k prozorro -v`
Expected: 2 passed.

- [ ] **Step 5: Delete the now-unused fixture**

Remove `tests/fixtures/prozorro_page.json` (no longer referenced). Verify nothing else references it: `grep -r prozorro_page tests/` returns nothing.

- [ ] **Step 6: Commit**

```bash
git add src/recovery/stage1_ingest.py tests/test_stage1_ingest.py
git rm tests/fixtures/prozorro_page.json
git commit -m "feat: pull_prozorro walks descending feed + per-id fetch + CPV filter"
```

---

### Task 3: rewrite `pull_spending`

**Files:**
- Modify: `src/recovery/stage1_ingest.py`
- Test: `tests/test_stage1_ingest.py`

- [ ] **Step 1: Replace the spending test** in `tests/test_stage1_ingest.py`

Remove the existing `test_pull_spending_returns_records` and `spending_page.json` usage. Add `from datetime import date` at the top. New test:

```python
@respx.mock
def test_pull_spending_batches_edrpous_and_windows(tmp_path):
    seen = []

    def handler(request):
        seen.append({
            "recipt_edrpous": request.url.params.get("recipt_edrpous"),
            "startdate": request.url.params.get("startdate"),
            "enddate": request.url.params.get("enddate"),
        })
        edr = request.url.params.get("recipt_edrpous").split(",")[0]
        return httpx.Response(200, json=[{
            "id": 1, "recipt_edrpou": edr, "recipt_name": "X",
            "amount": 10.0, "trans_date": "2025-10-01", "payment_details": "y",
        }])

    respx.route(host="api.spending.gov.ua").mock(side_effect=handler)

    out = pull_spending(cache_dir=tmp_path, edrpous=["1", "2", "3"],
                        batch=2, window_days=90, months=12, today=date(2026, 6, 3))

    # 2 batches (["1","2"], ["3"]) x 4 quarterly windows = 8 requests
    assert len(seen) == 8
    assert seen[0]["recipt_edrpous"] == "1,2"   # batched, comma-joined
    assert any(s["recipt_edrpous"] == "3" for s in seen)
    for s in seen:                              # every window within the 92-day API limit
        span = (date.fromisoformat(s["enddate"]) - date.fromisoformat(s["startdate"])).days
        assert span <= 90
    assert len(out) == 8                        # bare-list rows concatenated
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_stage1_ingest.py -k spending -v`
Expected: FAIL (current `pull_spending` uses singular `recipt_edrpou`, wrong path, expects `data["items"]`).

- [ ] **Step 3: Add the window helper and replace `pull_spending`** in `src/recovery/stage1_ingest.py`

Add `from datetime import date, timedelta` at the top of the file. Then:

```python
def _quarter_windows(today: date, months: int, window_days: int) -> list[tuple[str, str]]:
    """Contiguous (startdate, enddate) ISO pairs covering the last `months`, each spanning
    at most `window_days` days (the spending API caps a query at 92 days)."""
    start_all = today - timedelta(days=months * 30)
    windows: list[tuple[str, str]] = []
    cur_end = today
    while cur_end > start_all:
        cur_start = max(start_all, cur_end - timedelta(days=window_days))
        windows.append((cur_start.isoformat(), cur_end.isoformat()))
        cur_end = cur_start - timedelta(days=1)
    return windows


def pull_spending(cache_dir: Path, edrpous: list[str],
                  batch: int = config.SPENDING_BATCH,
                  window_days: int = config.SPENDING_WINDOW_DAYS,
                  months: int = config.WINDOW_MONTHS,
                  today: date | None = None) -> list[dict]:
    """Pull treasury transactions for the given recipient EDRPOUs, batching EDRPOUs into
    `recipt_edrpous` and chunking the date range into <=`window_days` windows."""
    if today is None:
        today = date.today()
    uniq = sorted({e for e in edrpous if e})
    windows = _quarter_windows(today, months, window_days)
    out: list[dict] = []
    with CachedClient(cache_dir / "spending") as client:
        for i in range(0, len(uniq), batch):
            recipt = ",".join(uniq[i:i + batch])
            for start, end in windows:
                try:
                    rows = client.get_json(
                        f"{config.SPENDING_API}/v2/api/transactions/",
                        params={"recipt_edrpous": recipt, "startdate": start, "enddate": end},
                    )
                except Exception:
                    continue  # skip a failed batch/window; keep going
                if isinstance(rows, list):
                    out.extend(rows)
    print(f"spending: queried {len(uniq)} EDRPOUs over {len(windows)} windows, {len(out)} rows")
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_stage1_ingest.py -k spending -v`
Expected: 1 passed.

- [ ] **Step 5: Delete the now-unused fixture**

Remove `tests/fixtures/spending_page.json`. (The TED test still uses `tests/fixtures/ted_page.json` — keep that one.)

- [ ] **Step 6: Run the whole ingest test file + full suite**

Run: `.venv/Scripts/python -m pytest tests/test_stage1_ingest.py -v` then `.venv/Scripts/python -m pytest -q`
Expected: all pass (the TED test `test_pull_ted_returns_records` is unchanged and still passes).

- [ ] **Step 7: Commit**

```bash
git add src/recovery/stage1_ingest.py tests/test_stage1_ingest.py
git rm tests/fixtures/spending_page.json
git commit -m "feat: pull_spending uses real transactions endpoint with EDRPOU batching + quarterly windows"
```

---

### Task 4: `normalize_prozorro` region fallback

**Files:**
- Modify: `src/recovery/stage2_normalize.py`
- Test: `tests/test_stage2_normalize.py`

- [ ] **Step 1: Add a failing test** (append to `tests/test_stage2_normalize.py`)

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_stage2_normalize.py::test_normalize_prozorro_region_falls_back_to_supplier_address -v`
Expected: FAIL (region is None — current code only reads items[0].deliveryAddress.region).

- [ ] **Step 3: Update the region line in `normalize_prozorro`** (`src/recovery/stage2_normalize.py`)

Find:
```python
        region = (items[0].get("deliveryAddress") or {}).get("region")
```
Replace with:
```python
        region = ((items[0].get("deliveryAddress") or {}).get("region")
                  or (sup.get("address") or {}).get("region"))
```
(`sup` is already defined above as `suppliers[0]`.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_stage2_normalize.py -v`
Expected: all pass (existing prozorro test still passes — its fixture has a deliveryAddress region, which still takes priority).

- [ ] **Step 5: Commit**

```bash
git add src/recovery/stage2_normalize.py tests/test_stage2_normalize.py
git commit -m "feat: normalize_prozorro falls back to supplier address region"
```

---

### Task 5: `run.py` — TED non-fatal + new signatures + CLI

**Files:**
- Modify: `run.py`
- Test: `tests/test_run_smoke.py`

- [ ] **Step 1: Add a failing test** (append to `tests/test_run_smoke.py`)

```python
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

    import polars as pl
    chain = pl.read_parquet(tmp_path / "chain.parquet")
    row = chain.to_dicts()[0]
    # TED failed -> overlay empty -> a paid contract with no TED is payment_no_ted
    assert row["state"] == "payment_no_ted"
    assert row["ted_id"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_run_smoke.py::test_pipeline_ted_nonfatal -v`
Expected: FAIL (current `main()` has no `target`/`scan_cap` kwargs and lets the TED error propagate).

- [ ] **Step 3: Replace `run.py`** with:

```python
import argparse

from recovery import config
from recovery import stage1_ingest as stage1
from recovery.stage2_normalize import normalize_prozorro, normalize_spending, normalize_ted
from recovery.stage3_join import join_core, attach_ted_overlay
from recovery.stage4_chain import build_chain, build_funnel


def main(target: int = config.PROZORRO_TARGET, scan_cap: int = config.PROZORRO_SCAN_CAP) -> None:
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_pz = stage1.pull_prozorro(cache_dir=config.CACHE_DIR, target=target, scan_cap=scan_cap)
    contracts = normalize_prozorro(raw_pz)

    edrpous = contracts["supplier_edrpou"].drop_nulls().unique().to_list()
    raw_sp = stage1.pull_spending(cache_dir=config.CACHE_DIR, edrpous=edrpous)
    spending = normalize_spending(raw_sp)

    try:
        raw_ted = stage1.pull_ted(cache_dir=config.CACHE_DIR)
        ted = normalize_ted(raw_ted)
    except Exception as exc:  # TED v3 is best-effort; keep the pipeline running without it
        print(f"TED ingest skipped (non-fatal): {exc}")
        ted = normalize_ted([])

    contracts.write_parquet(config.OUT_DIR / "prozorro_contracts.parquet")
    spending.write_parquet(config.OUT_DIR / "spending_tx.parquet")
    ted.write_parquet(config.OUT_DIR / "ted_notices.parquet")

    joined = attach_ted_overlay(join_core(contracts, spending), ted)
    chain = build_chain(joined)
    funnel = build_funnel(joined)

    chain.write_parquet(config.OUT_DIR / "chain.parquet")
    funnel.write_parquet(config.OUT_DIR / "funnel.parquet")
    print(f"Wrote {chain.height} chain rows to {config.OUT_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=config.PROZORRO_TARGET,
                        help="stop after this many in-scope contracts")
    parser.add_argument("--scan-cap", type=int, default=config.PROZORRO_SCAN_CAP,
                        help="stop after scanning this many feed stubs")
    args = parser.parse_args()
    main(target=args.target, scan_cap=args.scan_cap)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_run_smoke.py -v`
Expected: both smoke tests pass (the existing `test_pipeline_writes_chain` still works — its monkeypatched `pull_*` lambdas accept `**k`, and `pull_ted` returns a matching TED row so its chain row is `full`).

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add run.py tests/test_run_smoke.py
git commit -m "feat: run.py new ingest signatures, TED non-fatal, --target/--scan-cap CLI"
```

---

### Task 6: README — real-data ingest

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update `README.md`**

Read the current `README.md`. Update the data-acquisition / quickstart area to:
- State that `python run.py` now performs a **real** live-API pull: ProZorro newest-first
  reconstruction contracts (bounded to ~500 via `--target`, scanning up to `--scan-cap`
  feed stubs) joined to real spending.gov.ua treasury payments (batched recipient EDRPOUs,
  quarterly ≤92-day windows over the last 12 months). Note the first run takes ~5–10 minutes
  and is cached to `data/cache/` (re-runs are fast).
- Note that **TED ingest is currently deferred** (its v3 search returns 400 with the present
  query) and is **non-fatal**: the pipeline completes on ProZorro + spending and the TED
  overlay is simply empty until the TED request format is fixed.
- Keep `python scripts/seed_demo.py` documented as the instant offline-demo alternative.
- Keep the honesty note that this is a **bounded sample** (newest ~500 reconstruction
  contracts), not the full corpus.
Write clearly, in English, matching the existing tone.

- [ ] **Step 2: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document real-data ingest (ProZorro + spending, TED deferred)"
```

---

## Self-Review

**Spec coverage:**
- config bounds → Task 1. ✓
- pull_prozorro descending-feed walk + per-id fetch + CPV filter + target/scan_cap → Task 2. ✓
- pull_spending real endpoint + recipt_edrpous batching + quarterly ≤92-day windows + bare-list concat → Task 3. ✓
- normalize_prozorro region fallback → Task 4. ✓
- run.py TED non-fatal + new signatures + CLI → Task 5. ✓
- Injectable `today` for deterministic window tests → Task 3 (`pull_spending(..., today=)`). ✓
- Error handling: per-contract skip (Task 2 try/except), per-batch skip (Task 3 try/except), TED non-fatal (Task 5). ✓
- Honest logging (scanned vs kept; EDRPOUs/windows/rows) → Tasks 2, 3 print lines. ✓
- Tests with real shapes via respx → Tasks 2, 3. ✓
- README → Task 6. ✓

**Out-of-scope confirmed absent:** TED fix, contractId-level join, kpk/donor tagging, region_id enrichment, async, bulk dumps. Not in any task. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code. Task 6 is documentation prose (acceptable).

**Type/signature consistency:** `pull_prozorro(cache_dir, target, scan_cap)` and `pull_spending(cache_dir, edrpous, batch, window_days, months, today)` are defined in Tasks 2/3 and called with matching kwargs in Task 5's `run.py` (`pull_prozorro(cache_dir=, target=, scan_cap=)`, `pull_spending(cache_dir=, edrpous=)`). `_quarter_windows(today, months, window_days)` is internal to Task 3. `normalize_prozorro` keeps its signature (Task 4 only changes the region expression). The smoke-test monkeypatches use `**k`, so they tolerate the new kwargs. Config names (`PROZORRO_TARGET`, `PROZORRO_SCAN_CAP`, `SPENDING_BATCH`, `SPENDING_WINDOW_DAYS`) are consistent across Tasks 1, 2, 3, 5. ✓
