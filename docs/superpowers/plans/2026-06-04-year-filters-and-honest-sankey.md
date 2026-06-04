# Year filters + honest magnitude bars — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add contract-year and payment-year filters to the dashboard, and replace the misleading Sankey with honest labelled magnitude bars (paid is supplier-level treasury inflow).

**Architecture:** Carry `contract_year` through the pipeline into `chain.parquet`; write a `paid_by_year.parquet` side table for year-accurate payment sums. A `_scope()` helper in `queries.py` produces the filtered relation every query reads from. The frontend gains two year selects and swaps the d3-sankey for plain bars.

**Tech Stack:** Python 3.12, polars, DuckDB, FastAPI, vanilla JS + d3 (d3-sankey removed).

**Spec:** `docs/superpowers/specs/2026-06-04-year-filters-and-honest-sankey-design.md`

**Run tests with:** `.venv/Scripts/python.exe -m pytest` (Windows venv). Commit after each task.

---

### Task 1: `contract_year` in normalize_prozorro

**Files:**
- Modify: `src/recovery/stage2_normalize.py` (`_PROZORRO_SCHEMA` ~line 5-9, `normalize_prozorro` ~line 22-42)
- Test: `tests/test_stage2_normalize.py`

- [ ] **Step 1: Write the failing test** — add to `tests/test_stage2_normalize.py`:

```python
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
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stage2_normalize.py::test_normalize_prozorro_parses_contract_year -v`
Expected: FAIL — `KeyError: 'contract_year'` (column not in schema).

- [ ] **Step 3: Implement.** In `src/recovery/stage2_normalize.py`, add to `_PROZORRO_SCHEMA` (after `"redacted": pl.Boolean,`):

```python
    "contract_year": pl.Int64,
```

In `normalize_prozorro`, inside the `rows.append({...})` dict (after `"redacted": ...`), add:

```python
            "contract_year": (
                int(r["dateSigned"][:4])
                if r.get("dateSigned") and r["dateSigned"][:4].isdigit()
                else None
            ),
```

- [ ] **Step 4: Update the empty-schema test.** In `tests/test_stage2_normalize.py`, `test_normalize_empty_input_keeps_schema` asserts the exact column list — append `"contract_year"`:

```python
    assert normalize_prozorro([]).columns == [
        "contract_id", "cpv", "cpv_div", "supplier_edrpou", "supplier_name",
        "supplier_name_norm", "amount_uah", "region", "redacted", "contract_year",
    ]
```

- [ ] **Step 5: Run tests, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stage2_normalize.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/recovery/stage2_normalize.py tests/test_stage2_normalize.py
git commit -m "feat: parse contract_year from ProZorro dateSigned"
```

---

### Task 2: `paid_by_year` side table + carry `contract_year` into chain

**Files:**
- Modify: `src/recovery/stage3_join.py` (add `build_paid_by_year`)
- Modify: `src/recovery/stage4_chain.py` (`build_chain` select ~line 15-20)
- Modify: `run.py` (write the new parquet)
- Test: `tests/test_stage3_join.py`, `tests/test_stage4_chain.py`

- [ ] **Step 1: Write failing test** — add to `tests/test_stage3_join.py`:

```python
from recovery.stage3_join import build_paid_by_year  # add to existing imports


def test_build_paid_by_year_aggregates_per_contract_and_year():
    contracts = pl.DataFrame({
        "contract_id": ["c1", "c2"],
        "supplier_edrpou": ["111", "222"],
    })
    spending = pl.DataFrame({
        "recipient_edrpou": ["111", "111", "222"],
        "amount_uah": [10.0, 5.0, 7.0],
        "payment_date": ["2024-03-01", "2025-01-09", "2024-12-31"],
    })
    out = build_paid_by_year(contracts, spending).sort(["contract_id", "year"])
    rows = out.to_dicts()
    assert rows == [
        {"contract_id": "c1", "year": 2024, "paid_uah": 10.0},
        {"contract_id": "c1", "year": 2025, "paid_uah": 5.0},
        {"contract_id": "c2", "year": 2024, "paid_uah": 7.0},
    ]
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stage3_join.py::test_build_paid_by_year_aggregates_per_contract_and_year -v`
Expected: FAIL — `ImportError: cannot import name 'build_paid_by_year'`.

- [ ] **Step 3: Implement** in `src/recovery/stage3_join.py` (append at end of file):

```python
def build_paid_by_year(contracts: pl.DataFrame, spending: pl.DataFrame) -> pl.DataFrame:
    """Payments per contract per calendar year of payment_date.

    Treasury rows carry no contractId, so payments attach to a contract via its
    supplier EDRPOU (the same supplier-level attribution as the lifetime total).
    """
    spend_year = (
        spending.with_columns(
            pl.col("payment_date").str.slice(0, 4).cast(pl.Int64).alias("year")
        )
        .group_by(["recipient_edrpou", "year"])
        .agg(pl.col("amount_uah").sum().alias("paid_uah"))
    )
    return (
        contracts.select("contract_id", "supplier_edrpou")
        .join(spend_year, left_on="supplier_edrpou", right_on="recipient_edrpou", how="inner")
        .select("contract_id", "year", "paid_uah")
    )
```

- [ ] **Step 4: Carry `contract_year` into the chain.** In `src/recovery/stage4_chain.py`, `build_chain`'s `.select(...)` — add `"contract_year"` to the selected columns (after `"region",`):

```python
    return joined.with_columns(state.alias("state")).select(
        "contract_id", "supplier_edrpou", "supplier_name", "cpv_div", "region",
        "contract_year",
        "contract_amount_uah", "paid_amount_uah",
        pl.col("amount_eur").alias("ted_amount_eur"),
        "ted_id", "ted_match_confidence", "state",
    )
```

- [ ] **Step 5: Add a chain-carries-year test** — add to `tests/test_stage4_chain.py` (reuse that file's existing joined-frame builder pattern; this minimal standalone works):

```python
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
```

- [ ] **Step 6: Wire run.py.** In `run.py`, add the import line (top, with the stage3 import):

```python
from recovery.stage3_join import join_core, attach_ted_overlay, build_paid_by_year
```

After `spending = normalize_spending(raw_sp)` and before the parquet writes, add:

```python
    paid_by_year = build_paid_by_year(contracts, spending)
```

After `spending.write_parquet(config.OUT_DIR / "spending_tx.parquet")`, add:

```python
    paid_by_year.write_parquet(config.OUT_DIR / "paid_by_year.parquet")
```

- [ ] **Step 7: Run tests, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stage3_join.py tests/test_stage4_chain.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/recovery/stage3_join.py src/recovery/stage4_chain.py run.py tests/test_stage3_join.py tests/test_stage4_chain.py
git commit -m "feat: paid_by_year side table + contract_year in chain"
```

---

### Task 3: `_scope` helper + year params in queries

**Files:**
- Modify: `src/recovery/queries.py` (replace `_where`; update `kpi`, `sankey`, `breakdown`, `top`, `gaps`; add `years`)
- Test: `tests/test_queries.py`

- [ ] **Step 1: Write failing tests** — add to `tests/test_queries.py` (it has a fixture that writes a `chain.parquet`; these tests write their own tmp data to be self-contained):

```python
import polars as pl
from pathlib import Path
from recovery import queries


def _write_chain(tmp_path, rows):
    pl.DataFrame(rows).write_parquet(Path(tmp_path) / "chain.parquet")


def test_kpi_filters_by_contract_year(tmp_path):
    _write_chain(tmp_path, [
        {"contract_id": "c1", "supplier_edrpou": "1", "supplier_name": "A", "cpv_div": "45",
         "region": "Київ", "contract_year": 2023, "contract_amount_uah": 100.0,
         "paid_amount_uah": 10.0, "ted_amount_eur": None, "ted_id": None,
         "ted_match_confidence": None, "state": "payment_no_ted"},
        {"contract_id": "c2", "supplier_edrpou": "2", "supplier_name": "B", "cpv_div": "45",
         "region": "Київ", "contract_year": 2024, "contract_amount_uah": 200.0,
         "paid_amount_uah": 20.0, "ted_amount_eur": None, "ted_id": None,
         "ted_match_confidence": None, "state": "payment_no_ted"},
    ])
    assert queries.kpi(tmp_path, contract_year=2023)["contracted_uah"] == 100


def test_kpi_payment_year_uses_year_specific_paid(tmp_path):
    _write_chain(tmp_path, [
        {"contract_id": "c1", "supplier_edrpou": "1", "supplier_name": "A", "cpv_div": "45",
         "region": "Київ", "contract_year": 2023, "contract_amount_uah": 100.0,
         "paid_amount_uah": 30.0, "ted_amount_eur": None, "ted_id": None,
         "ted_match_confidence": None, "state": "payment_no_ted"},
    ])
    pl.DataFrame({"contract_id": ["c1", "c1"], "year": [2023, 2024], "paid_uah": [10.0, 20.0]}) \
        .write_parquet(Path(tmp_path) / "paid_by_year.parquet")
    assert queries.kpi(tmp_path, payment_year=2024)["paid_uah"] == 20


def test_years_lists_contract_and_payment_years(tmp_path):
    _write_chain(tmp_path, [
        {"contract_id": "c1", "supplier_edrpou": "1", "supplier_name": "A", "cpv_div": "45",
         "region": "Київ", "contract_year": 2023, "contract_amount_uah": 100.0,
         "paid_amount_uah": 0.0, "ted_amount_eur": None, "ted_id": None,
         "ted_match_confidence": None, "state": "contract_no_payment"},
    ])
    pl.DataFrame({"contract_id": ["c1"], "year": [2024], "paid_uah": [5.0]}) \
        .write_parquet(Path(tmp_path) / "paid_by_year.parquet")
    out = queries.years(tmp_path)
    assert out["contract_years"] == [2023]
    assert out["payment_years"] == [2024]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_queries.py -k "contract_year or payment_year or years_lists" -v`
Expected: FAIL — `kpi() got an unexpected keyword argument 'contract_year'` / `module 'queries' has no attribute 'years'`.

- [ ] **Step 3: Replace `_where` with `_scope`.** In `src/recovery/queries.py`, delete the `_where` function and add:

```python
def _scope(out_dir, sector=None, region=None, contract_year=None, payment_year=None):
    """Return (from_sql, where_sql, params): a relation aliased `q` (with paid_amount_uah
    swapped to the selected payment year when set), an outer WHERE clause (possibly ''), and
    bound params. Compose in each query as: FROM {from_sql} {where_sql}."""
    clauses, where_params = [], []
    if sector:
        clauses.append("q.cpv_div = ?"); where_params.append(sector)
    if region:
        clauses.append("q.region = ?"); where_params.append(region)
    if contract_year:
        clauses.append("q.contract_year = ?"); where_params.append(int(contract_year))
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    pby_path = Path(out_dir) / "paid_by_year.parquet"
    if payment_year and pby_path.exists():  # ignore the filter if the side table isn't built yet
        pby = str(pby_path).replace("\\", "/")
        from_sql = (
            "(SELECT c.* REPLACE (py.paid_uah AS paid_amount_uah) FROM chain c "
            "JOIN (SELECT contract_id, SUM(paid_uah) AS paid_uah "
            f"FROM read_parquet('{pby}') WHERE year = ? GROUP BY contract_id) py "
            "ON c.contract_id = py.contract_id) q"
        )
        params = [int(payment_year)] + where_params  # subquery's year `?` precedes the WHERE `?`s
    else:
        from_sql = "chain q"
        params = where_params
    return from_sql, where_sql, params
```

- [ ] **Step 4: Thread params through `kpi`, `sankey`, `breakdown`, `top`, `gaps`.** Each currently builds `_where(...)` and does `FROM chain {where}`. Change each signature to accept `contract_year=None, payment_year=None`, call `_scope`, and use `FROM {from_sql} {where_sql}`. Concretely:

`kpi`:
```python
def kpi(out_dir: Path, sector: str | None = None, region: str | None = None,
        contract_year: int | None = None, payment_year: int | None = None) -> dict:
    con = _conn(out_dir)
    from_sql, where_sql, params = _scope(out_dir, sector, region, contract_year, payment_year)
    row = con.execute(
        f"""SELECT
              COALESCE(SUM(contract_amount_uah), 0) AS contracted,
              COALESCE(SUM(paid_amount_uah), 0) AS paid,
              COALESCE(SUM(ted_amount_eur), 0) AS announced_eur,
              COALESCE(SUM(CASE WHEN state = 'contract_no_payment' THEN 1 ELSE 0 END), 0) AS breaks
            FROM {from_sql} {where_sql}""",
        params,
    ).fetchone()
    con.close()
    return {
        "contracted_uah": int(row[0]), "paid_uah": int(row[1]),
        "announced_eur": int(row[2]), "breaks": int(row[3]),
    }
```

`sankey`:
```python
def sankey(out_dir: Path, sector: str | None = None, region: str | None = None,
           contract_year: int | None = None, payment_year: int | None = None) -> dict:
    con = _conn(out_dir)
    from_sql, where_sql, params = _scope(out_dir, sector, region, contract_year, payment_year)
    row = con.execute(
        f"""SELECT
              COALESCE(SUM(ted_amount_eur), 0),
              COALESCE(SUM(contract_amount_uah), 0),
              COALESCE(SUM(paid_amount_uah), 0)
            FROM {from_sql} {where_sql}""",
        params,
    ).fetchone()
    con.close()
    nodes = [{"name": "Оголошено (TED)"}, {"name": "Законтрактовано"}, {"name": "Надходження постачальникам"}]
    links = [
        {"source": 0, "target": 1, "value": int(row[1])},
        {"source": 1, "target": 2, "value": int(row[2])},
    ]
    return {"nodes": nodes, "links": links, "announced_eur": int(row[0])}
```

`breakdown`:
```python
def breakdown(out_dir: Path, sector: str | None = None, region: str | None = None,
              contract_year: int | None = None, payment_year: int | None = None) -> list[dict]:
    con = _conn(out_dir)
    from_sql, where_sql, params = _scope(out_dir, sector, region, contract_year, payment_year)
    rows = con.execute(
        f"""SELECT state,
              COUNT(*) AS cnt,
              COALESCE(SUM(contract_amount_uah), 0) AS contracted,
              COALESCE(SUM(paid_amount_uah), 0) AS paid
            FROM {from_sql} {where_sql}
            GROUP BY state ORDER BY state""",
        params,
    ).fetchall()
    con.close()
    return [
        {"state": r[0], "count": int(r[1]),
         "contracted_uah": int(r[2]), "paid_uah": int(r[3])}
        for r in rows
    ]
```

`top` — change signature and both queries' `FROM chain {where}` to `FROM {from_sql} {where_sql}`:
```python
def top(out_dir: Path, by: str, sector: str | None = None,
        region: str | None = None, contract_year: int | None = None,
        payment_year: int | None = None, limit: int = 10) -> list[dict]:
    if by not in ("supplier", "region"):
        raise ValueError(f"invalid 'by': {by!r} (expected 'supplier' or 'region')")
    con = _conn(out_dir)
    from_sql, where_sql, params = _scope(out_dir, sector, region, contract_year, payment_year)
    if by == "supplier":
        rows = con.execute(
            f"""SELECT supplier_edrpou, any_value(supplier_name) AS name,
                  COALESCE(SUM(contract_amount_uah), 0) AS contracted,
                  COALESCE(SUM(paid_amount_uah), 0) AS paid,
                  COUNT(*) AS n
                FROM {from_sql} {where_sql}
                GROUP BY supplier_edrpou
                ORDER BY contracted DESC LIMIT ?""",
            params + [limit],
        ).fetchall()
        con.close()
        return [
            {"edrpou": r[0], "supplier_name": r[1], "contracted_uah": int(r[2]),
             "paid_uah": int(r[3]), "contracts": int(r[4])}
            for r in rows
        ]
    rows = con.execute(
        f"""SELECT region,
              COALESCE(SUM(contract_amount_uah), 0) AS contracted,
              COALESCE(SUM(paid_amount_uah), 0) AS paid,
              COUNT(*) AS n
            FROM {from_sql} {where_sql}
            GROUP BY region
            ORDER BY contracted DESC LIMIT ?""",
        params + [limit],
    ).fetchall()
    con.close()
    return [
        {"region": r[0], "contracted_uah": int(r[1]),
         "paid_uah": int(r[2]), "contracts": int(r[3])}
        for r in rows
    ]
```

`gaps` — append the `state` predicate to the outer WHERE, choosing the connector from whether
`where_sql` is already present (never sniff `from_sql`, since the payment-year subquery itself
contains the word WHERE):
```python
def gaps(out_dir: Path, gap_type: str = "contract_no_payment",
         sector: str | None = None, region: str | None = None,
         contract_year: int | None = None, payment_year: int | None = None) -> list[dict]:
    con = _conn(out_dir)
    from_sql, where_sql, params = _scope(out_dir, sector, region, contract_year, payment_year)
    state_clause = "AND q.state = ?" if where_sql else "WHERE q.state = ?"
    result = con.execute(
        "SELECT contract_id, supplier_name, supplier_edrpou, cpv_div, region, "
        f"contract_amount_uah, state FROM {from_sql} {where_sql} {state_clause}",
        params + [gap_type],
    ).to_arrow_table().to_pylist()
    con.close()
    return result
```

- [ ] **Step 5: Add the `years` function** to `src/recovery/queries.py`:

```python
def years(out_dir: Path) -> dict:
    con = _conn(out_dir)
    crows = con.execute(
        "SELECT DISTINCT contract_year FROM chain "
        "WHERE contract_year IS NOT NULL ORDER BY contract_year DESC"
    ).fetchall()
    payment_years: list[int] = []
    pby = Path(out_dir) / "paid_by_year.parquet"
    if pby.exists():
        path = str(pby).replace("\\", "/")
        prows = con.execute(
            f"SELECT DISTINCT year FROM read_parquet('{path}') "
            "WHERE year IS NOT NULL ORDER BY year DESC"
        ).fetchall()
        payment_years = [int(r[0]) for r in prows]
    con.close()
    return {"contract_years": [int(r[0]) for r in crows], "payment_years": payment_years}
```

- [ ] **Step 6: Run tests, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_queries.py -v`
Expected: PASS (existing tests still green — they call with sector/region only; new ones green).

- [ ] **Step 7: Commit**

```bash
git add src/recovery/queries.py tests/test_queries.py
git commit -m "feat: _scope helper + contract/payment year filters in queries"
```

---

### Task 4: API — year params + `/api/years`

**Files:**
- Modify: `api/app.py`
- Test: `tests/test_api.py`

- [ ] **Step 1a: Add `contract_year` to the test seed.** `test_api.py` uses a `_seed(out_dir)` helper; `/api/years` runs `SELECT contract_year FROM chain`, so the seed row needs the column. In `tests/test_api.py` `_seed`, add `"contract_year": 2024,` to the row dict (after `"state": "full"` — order doesn't matter):

```python
        {"contract_id": "c1", "supplier_edrpou": "1", "supplier_name": "A",
         "cpv_div": "45", "region": "Київ", "contract_amount_uah": 1000000,
         "paid_amount_uah": 750000, "ted_amount_eur": 500000, "ted_id": "t1",
         "ted_match_confidence": 1.0, "state": "full", "contract_year": 2024},
```

- [ ] **Step 1b: Write failing tests** — add to `tests/test_api.py`, following its `_seed`/`_client` pattern (no `client` fixture exists):

```python
def test_years_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/years")
    assert resp.status_code == 200
    body = resp.json()
    assert body["contract_years"] == [2024]
    assert body["payment_years"] == []  # no paid_by_year.parquet seeded


def test_kpi_accepts_year_params(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    # payment_year is ignored when no paid_by_year.parquet exists (see _scope guard)
    resp = client.get("/api/kpi?contract_year=2024&payment_year=2025")
    assert resp.status_code == 200
    assert resp.json()["contracted_uah"] == 1000000
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k "years_endpoint or year_params" -v`
Expected: FAIL — 404 for `/api/years`.

- [ ] **Step 3: Implement** in `api/app.py`. Add `contract_year`/`payment_year` params to `get_kpi`, `get_sankey`, `get_breakdown`, `get_top`, `get_gaps`, and add the years route. Example for `get_kpi` (apply the same two params + pass-through to the others):

```python
@app.get("/api/kpi")
def get_kpi(sector: str | None = None, region: str | None = None,
            contract_year: int | None = None, payment_year: int | None = None):
    return queries.kpi(config.OUT_DIR, sector=sector, region=region,
                       contract_year=contract_year, payment_year=payment_year)
```

`get_sankey`, `get_breakdown`: identical param additions, pass through to `queries.sankey` / `queries.breakdown`.

`get_top`:
```python
@app.get("/api/top")
def get_top(by: Literal["supplier", "region"] = "supplier",
            sector: str | None = None, region: str | None = None,
            contract_year: int | None = None, payment_year: int | None = None,
            limit: int = Query(default=10, ge=1, le=200)):
    return queries.top(config.OUT_DIR, by=by, sector=sector, region=region,
                       contract_year=contract_year, payment_year=payment_year, limit=limit)
```

`get_gaps`:
```python
@app.get("/api/gaps")
def get_gaps(gap_type: str = Query("contract_no_payment", alias="type"),
             sector: str | None = None, region: str | None = None,
             contract_year: int | None = None, payment_year: int | None = None):
    return queries.gaps(config.OUT_DIR, gap_type=gap_type, sector=sector, region=region,
                        contract_year=contract_year, payment_year=payment_year)
```

New route (place after `get_regions`):
```python
@app.get("/api/years")
def get_years():
    return queries.years(config.OUT_DIR)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app.py tests/test_api.py
git commit -m "feat: API year params + /api/years endpoint"
```

---

### Task 5: Frontend — year selects + filter wiring

**Files:**
- Modify: `web/index.html` (filters block ~line 15-28)
- Modify: `web/app.js` (`state` line 9, `q()` 11-17, add `initYears`, `wire` 223-249, bootstrap 251-253)

- [ ] **Step 1: Add the selects** in `web/index.html`, inside `<div class="filters">` after the region `<label>` (line 27):

```html
      <label>Рік контракту:
        <select id="contract-year"><option value="">усі</option></select>
      </label>
      <label>Рік виплати:
        <select id="payment-year"><option value="">усі</option></select>
      </label>
```

- [ ] **Step 2: Extend client state + query string** in `web/app.js`. Replace the `state` declaration (line 9):

```javascript
const state = { sector: "", region: "", contractYear: "", paymentYear: "",
  gaps: [], gapSort: { key: "contract_amount_uah", dir: -1 } };
```

Replace `q()` (lines 11-17):

```javascript
function q() {
  const p = new URLSearchParams();
  if (state.sector) p.set("sector", state.sector);
  if (state.region) p.set("region", state.region);
  if (state.contractYear) p.set("contract_year", state.contractYear);
  if (state.paymentYear) p.set("payment_year", state.paymentYear);
  const s = p.toString();
  return s ? `?${s}` : "";
}
```

- [ ] **Step 3: Populate the year selects.** Add this function near `initRegions` (after line 221):

```javascript
async function initYears() {
  try {
    const y = await getJSON("/api/years");
    const fill = (id, vals) => {
      const sel = document.getElementById(id);
      (vals || []).forEach((v) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = v; sel.appendChild(o);
      });
    };
    fill("contract-year", y.contract_years);
    fill("payment-year", y.payment_years);
  } catch (e) { console.error(e); }
}
```

- [ ] **Step 4: Wire the selects.** In `wire()` (after the region listener, line 230), add:

```javascript
  document.getElementById("contract-year").addEventListener("change", (e) => {
    state.contractYear = e.target.value; onFilter();
  });
  document.getElementById("payment-year").addEventListener("change", (e) => {
    state.paymentYear = e.target.value; onFilter();
  });
```

- [ ] **Step 5: Call `initYears` on boot.** Replace the bootstrap lines (251-253):

```javascript
initRegions();
initYears();
wire();
refresh();
```

- [ ] **Step 6: Manual verify.** Run `.venv/Scripts/python.exe scripts/seed_demo.py` then start the server and load `/`; confirm both year selects populate and changing them re-renders without console errors. (Seed_demo gets `paid_by_year` in Task 6; until then payment-year may be empty — acceptable.)

- [ ] **Step 7: Commit**

```bash
git add web/index.html web/app.js
git commit -m "feat: contract/payment year selects in dashboard"
```

---

### Task 6: Frontend — magnitude bars + honest paid labels; seed_demo side table

**Files:**
- Modify: `web/index.html` (remove d3-sankey script line 9; the `#sankey` svg block ~line 41-43)
- Modify: `web/app.js` (`renderKpi` 37-50, replace `renderSankey` 81-114, `refresh` 200, `wire` ResizeObserver 242-248)
- Modify: `scripts/seed_demo.py` (write `paid_by_year.parquet`)

- [ ] **Step 1: Relabel paid in KPI.** In `web/app.js` `renderKpi` (lines 41-49), change the announced/paid cards:

```javascript
    <div class="kpi"><div class="label">Оголошено (TED), €</div>
      <div class="value">${fmt(k.announced_eur)}</div></div>
    <div class="kpi"><div class="label">Законтрактовано, грн</div>
      <div class="value">${fmt(k.contracted_uah)}</div></div>
    <div class="kpi"><div class="label">Надходження постачальникам, грн</div>
      <div class="value">${fmt(k.paid_uah)}</div>
      <div class="sub">усі казначейські виплати виконавцям, не лише за ці контракти</div></div>
    <div class="kpi break"><div class="label">Обриви (контракт без виплати)</div>
      <div class="value">${fmt(k.breaks)}</div></div>`;
```

- [ ] **Step 2: Replace the chart markup.** In `web/index.html`: delete the d3-sankey `<script>` (line 9). Replace the svg + note block (`<svg id="sankey"></svg>` and the `sankey-note` div) with:

```html
      <div id="magnitudes"></div>
      <div class="empty" id="magnitudes-note"></div>
```

Optionally also delete the now-unused d3 core `<script>` (line 8) if no other code uses `d3` — grep `web/app.js` for `d3.`; after this task the only use is removed, so delete line 8 too.

- [ ] **Step 3: Replace `renderSankey` with `renderMagnitudes`** in `web/app.js` (delete lines 81-114, insert):

```javascript
function renderMagnitudes(data) {
  const el = document.getElementById("magnitudes");
  const note = document.getElementById("magnitudes-note");
  const contracted = data.links?.[0]?.value || 0;
  const paid = data.links?.[1]?.value || 0;
  const announced = data.announced_eur || 0;
  const uahMax = Math.max(contracted, paid, 1);
  el.innerHTML =
    bar("Законтрактовано", contracted, uahMax, "funnel", `${fmt(contracted)} грн`) +
    bar("Надходження постачальникам", paid, uahMax, "payment_no_ted", `${fmt(paid)} грн`) +
    bar("Оголошено (TED)", announced, Math.max(announced, 1), "full", `€${fmt(announced)}`);
  note.textContent =
    "Суми у грн і € показані окремими шкалами. «Надходження» — усі казначейські виплати " +
    "постачальникам (дані не містять прив’язки до конкретного контракту), тому можуть " +
    "перевищувати законтрактовану суму.";
}
```

- [ ] **Step 4: Update orchestration.** In `web/app.js` `refresh()` (line 200), change `renderSankey(sankey);` to `renderMagnitudes(sankey);`. In `wire()`, delete the entire `ResizeObserver` block (lines 242-248) — bars reflow with the DOM, no redraw needed.

- [ ] **Step 5: seed_demo carries year + writes the side table.** In `scripts/seed_demo.py`, the rows are `dict(...)` with a `contract_id` like `"UA-2025-09-01-000001"` and a `paid_amount_uah`, but no `contract_year`. Immediately after the `rows = [ ... ]` literal and **before** `pl.DataFrame(rows).write_parquet(config.OUT_DIR / "chain.parquet")` (line 65), add the year (parsed from the contract id):

```python
for r in rows:
    r["contract_year"] = int(r["contract_id"].split("-")[1])
```

Then, after the funnel `write_parquet` block (line 74), add the side table:

```python
paid_rows = [
    {"contract_id": r["contract_id"], "year": r["contract_year"],
     "paid_uah": float(r["paid_amount_uah"])}
    for r in rows if r["paid_amount_uah"] > 0
]
pl.DataFrame(paid_rows, schema={"contract_id": pl.Utf8, "year": pl.Int64, "paid_uah": pl.Float64}) \
    .write_parquet(config.OUT_DIR / "paid_by_year.parquet")
```

(All demo contracts are 2025, so both year selects offer `2025` — enough to confirm the filter wiring.)

- [ ] **Step 6: Manual verify.** `.venv/Scripts/python.exe scripts/seed_demo.py`, start server, load `/`: three labelled bars render with numeric labels (no svg/sankey), KPI shows the relabeled paid card, both year selects populate and filter. No console errors; no reference to `d3` remains (grep).

- [ ] **Step 7: Commit**

```bash
git add web/index.html web/app.js scripts/seed_demo.py
git commit -m "feat: honest magnitude bars replace Sankey; relabel supplier inflow"
```

---

### Task 7: Full verification + live re-run

- [ ] **Step 1: Full test suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 2: Live pipeline** (writes `paid_by_year.parquet` + `contract_year`)

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe run.py --target 500 --scan-cap 1500`
Expected: completes; `data/out/paid_by_year.parquet` exists.

- [ ] **Step 3: Smoke the API**

Run: `curl -sS http://127.0.0.1:8000/api/years` then `curl -sS "http://127.0.0.1:8000/api/kpi?payment_year=2025"`
Expected: years lists populated; payment-year KPI returns a paid value ≤ the unfiltered paid.

- [ ] **Step 4: Push**

```bash
git push origin feature/real-data-ingest
```
