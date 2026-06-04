# UI Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the web dashboard into a single-scroll responsive page that surfaces the feasibility funnel, a state breakdown, top suppliers/regions, click-through supplier detail and context — backed by a few small new query endpoints — making it more informative and more responsive.

**Architecture:** Backend gains read-only DuckDB query functions (`regions`, `breakdown`, `top`) plus sector/region filters on `gaps`, each behind a thin FastAPI endpoint (same pattern as the existing five). Frontend stays no-build: a static `web/index.html` shell + `web/styles.css` + `web/app.js` (vanilla JS + d3 from CDN), served by the existing `StaticFiles` mount, fetching the JSON endpoints and re-rendering per-section on filter change.

**Tech Stack:** Python 3.12, DuckDB, polars, FastAPI, pytest; vanilla JS + d3@7/d3-sankey@0.12 (CDN).

---

## File Structure

```
src/recovery/queries.py     # MODIFY: add regions(), breakdown(), top(); extend gaps()
api/app.py                  # MODIFY: add /api/regions, /api/breakdown, /api/top; extend /api/gaps
web/index.html              # REWRITE: semantic shell loading styles.css + app.js
web/styles.css              # CREATE: responsive layout, state colors, cards, skeletons, modal
web/app.js                  # CREATE: fetch + per-section render + interactions
scripts/seed_demo.py        # COMMIT (already exists untracked): demo data for verification
tests/test_queries.py       # MODIFY: tests for regions/breakdown/top + extended gaps
tests/test_api.py           # MODIFY: tests for new/extended endpoints
README.md                   # MODIFY: document the dashboard + new endpoints
```

Existing `chain.parquet` columns (unchanged by this work): `contract_id, supplier_edrpou,
supplier_name, cpv_div, region, contract_amount_uah, paid_amount_uah, ted_amount_eur,
ted_id, ted_match_confidence, state`. `funnel.parquet`: `step, count`.

---

### Task 0: Commit the demo seeder

**Files:**
- Commit: `scripts/seed_demo.py` (already exists in the working tree, untracked)

`scripts/seed_demo.py` was created earlier to seed a synthetic `data/out/chain.parquet` +
`funnel.parquet` so the UI can be exercised without a live pull. The frontend tasks below
use it for verification, so commit it first.

- [ ] **Step 1: Confirm it runs**

Run: `.venv/Scripts/python scripts/seed_demo.py`
Expected: prints `Seeded 9 demo chain rows (5 paid, 2 with TED, 4 breaks) -> ...data\out`.

- [ ] **Step 2: Commit**

```bash
git add scripts/seed_demo.py
git commit -m "chore: add demo dataset seeder for UI verification"
```

---

### Task 1: `regions()` query + `/api/regions`

**Files:**
- Modify: `src/recovery/queries.py`
- Modify: `api/app.py`
- Test: `tests/test_queries.py`, `tests/test_api.py`

- [ ] **Step 1: Write the failing query test** (append to `tests/test_queries.py`)

```python
def test_regions_distinct_sorted(tmp_path):
    _seed(tmp_path)
    from recovery.queries import regions
    assert regions(tmp_path) == ["Київ", "Львів"]
```

(The existing `_seed` writes two rows with regions "Київ" and "Львів".)

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py::test_regions_distinct_sorted -v`
Expected: FAIL with `ImportError: cannot import name 'regions'`.

- [ ] **Step 3: Implement `regions` in `src/recovery/queries.py`** (add after `funnel`)

```python
def regions(out_dir: Path) -> list[str]:
    con = _conn(out_dir)
    rows = con.execute(
        "SELECT DISTINCT region FROM chain "
        "WHERE region IS NOT NULL AND region <> '' ORDER BY region"
    ).fetchall()
    con.close()
    return [r[0] for r in rows]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py::test_regions_distinct_sorted -v`
Expected: PASS.

- [ ] **Step 5: Write the failing API test** (append to `tests/test_api.py`)

```python
def test_regions_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/regions")
    assert resp.status_code == 200
    assert resp.json() == ["Київ", "Львів"]
```

- [ ] **Step 6: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_api.py::test_regions_endpoint -v`
Expected: FAIL (404 — route not defined).

- [ ] **Step 7: Add the endpoint to `api/app.py`** (after `get_funnel`)

```python
@app.get("/api/regions")
def get_regions():
    return queries.regions(config.OUT_DIR)
```

- [ ] **Step 8: Run both tests**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py::test_regions_distinct_sorted tests/test_api.py::test_regions_endpoint -v`
Expected: 2 passed.

- [ ] **Step 9: Commit**

```bash
git add src/recovery/queries.py api/app.py tests/test_queries.py tests/test_api.py
git commit -m "feat: regions query + /api/regions endpoint"
```

---

### Task 2: `breakdown()` query + `/api/breakdown`

**Files:**
- Modify: `src/recovery/queries.py`, `api/app.py`
- Test: `tests/test_queries.py`, `tests/test_api.py`

- [ ] **Step 1: Write the failing query test** (append to `tests/test_queries.py`)

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py -k breakdown -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `breakdown` in `src/recovery/queries.py`**

```python
def breakdown(out_dir: Path, sector: str | None = None, region: str | None = None) -> list[dict]:
    con = _conn(out_dir)
    where, params = _where(sector, region)
    rows = con.execute(
        f"""SELECT state,
              COUNT(*) AS cnt,
              COALESCE(SUM(contract_amount_uah), 0) AS contracted,
              COALESCE(SUM(paid_amount_uah), 0) AS paid
            FROM chain {where}
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

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py -k breakdown -v`
Expected: 2 passed.

- [ ] **Step 5: Write the failing API test** (append to `tests/test_api.py`)

```python
def test_breakdown_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/breakdown")
    assert resp.status_code == 200
    states = {r["state"] for r in resp.json()}
    assert states == {"full", "contract_no_payment"}
```

- [ ] **Step 6: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_api.py::test_breakdown_endpoint -v`
Expected: FAIL (404).

- [ ] **Step 7: Add the endpoint to `api/app.py`**

```python
@app.get("/api/breakdown")
def get_breakdown(sector: str | None = None, region: str | None = None):
    return queries.breakdown(config.OUT_DIR, sector=sector, region=region)
```

- [ ] **Step 8: Run both**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py -k breakdown tests/test_api.py::test_breakdown_endpoint -v`
Expected: 3 passed.

- [ ] **Step 9: Commit**

```bash
git add src/recovery/queries.py api/app.py tests/test_queries.py tests/test_api.py
git commit -m "feat: breakdown query + /api/breakdown endpoint"
```

---

### Task 3: `top()` query + `/api/top`

**Files:**
- Modify: `src/recovery/queries.py`, `api/app.py`
- Test: `tests/test_queries.py`, `tests/test_api.py`

- [ ] **Step 1: Write the failing query tests** (append to `tests/test_queries.py`)

```python
import pytest


def test_top_suppliers(tmp_path):
    _seed(tmp_path)
    from recovery.queries import top
    rows = top(tmp_path, by="supplier")
    # supplier "1" has the larger contract (1.0M) -> ranked first
    assert rows[0]["edrpou"] == "1"
    assert rows[0]["contracted_uah"] == 1000000
    assert rows[0]["contracts"] == 1


def test_top_regions(tmp_path):
    _seed(tmp_path)
    from recovery.queries import top
    rows = top(tmp_path, by="region")
    by_region = {r["region"]: r for r in rows}
    assert by_region["Київ"]["contracted_uah"] == 1000000
    assert by_region["Львів"]["contracted_uah"] == 500000


def test_top_rejects_bad_by(tmp_path):
    _seed(tmp_path)
    from recovery.queries import top
    with pytest.raises(ValueError):
        top(tmp_path, by="supplier; DROP TABLE chain")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py -k top_ -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `top` in `src/recovery/queries.py`**

```python
def top(out_dir: Path, by: str, sector: str | None = None,
        region: str | None = None, limit: int = 10) -> list[dict]:
    if by not in ("supplier", "region"):
        raise ValueError(f"invalid 'by': {by!r} (expected 'supplier' or 'region')")
    con = _conn(out_dir)
    where, params = _where(sector, region)
    if by == "supplier":
        rows = con.execute(
            f"""SELECT supplier_edrpou, any_value(supplier_name) AS name,
                  COALESCE(SUM(contract_amount_uah), 0) AS contracted,
                  COALESCE(SUM(paid_amount_uah), 0) AS paid,
                  COUNT(*) AS n
                FROM chain {where}
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
            FROM chain {where}
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

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py -k top_ -v`
Expected: 3 passed.

- [ ] **Step 5: Write the failing API tests** (append to `tests/test_api.py`)

```python
def test_top_suppliers_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/top?by=supplier")
    assert resp.status_code == 200
    assert resp.json()[0]["edrpou"] == "1"


def test_top_invalid_by_rejected(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/top?by=bogus")
    assert resp.status_code == 422  # FastAPI Literal validation
```

- [ ] **Step 6: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_api.py -k top -v`
Expected: FAIL (404 / wrong status).

- [ ] **Step 7: Add the endpoint to `api/app.py`** — also add `from typing import Literal` at the top

At the top of `api/app.py`, add the import:

```python
from typing import Literal
```

Then add the endpoint:

```python
@app.get("/api/top")
def get_top(by: Literal["supplier", "region"] = "supplier",
            sector: str | None = None, region: str | None = None, limit: int = 10):
    return queries.top(config.OUT_DIR, by=by, sector=sector, region=region, limit=limit)
```

- [ ] **Step 8: Run both**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py -k top_ tests/test_api.py -k top -v`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/recovery/queries.py api/app.py tests/test_queries.py tests/test_api.py
git commit -m "feat: top suppliers/regions query + /api/top endpoint (by allowlisted)"
```

---

### Task 4: extend `gaps()` with sector/region + supplier_edrpou

**Files:**
- Modify: `src/recovery/queries.py`, `api/app.py`
- Test: `tests/test_queries.py`, `tests/test_api.py`

- [ ] **Step 1: Write the failing query test** (append to `tests/test_queries.py`)

```python
def test_gaps_filtered_by_sector(tmp_path):
    _seed(tmp_path)
    from recovery.queries import gaps
    # seed: only c2 is contract_no_payment, in sector 71
    assert gaps(tmp_path, gap_type="contract_no_payment", sector="45") == []
    rows = gaps(tmp_path, gap_type="contract_no_payment", sector="71")
    assert len(rows) == 1
    assert rows[0]["contract_id"] == "c2"
    assert rows[0]["supplier_edrpou"] == "2"
```

(This relies on `gaps` rows now including `supplier_edrpou`.)

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py::test_gaps_filtered_by_sector -v`
Expected: FAIL (gaps has no sector kwarg / no supplier_edrpou key).

- [ ] **Step 3: Replace `gaps` in `src/recovery/queries.py`** with:

```python
def gaps(out_dir: Path, gap_type: str = "contract_no_payment",
         sector: str | None = None, region: str | None = None) -> list[dict]:
    con = _conn(out_dir)
    clauses, params = ["state = ?"], [gap_type]
    if sector:
        clauses.append("cpv_div = ?")
        params.append(sector)
    if region:
        clauses.append("region = ?")
        params.append(region)
    where = "WHERE " + " AND ".join(clauses)
    result = con.execute(
        "SELECT contract_id, supplier_name, supplier_edrpou, cpv_div, region, "
        f"contract_amount_uah, state FROM chain {where}",
        params,
    ).to_arrow_table().to_pylist()
    con.close()
    return result
```

- [ ] **Step 4: Run to verify it passes (and existing gaps tests still pass)**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py -k gaps -v`
Expected: all gaps tests pass (existing `test_gaps_lists_breaks`, `test_gaps_empty_returns_list`, new `test_gaps_filtered_by_sector`).

- [ ] **Step 5: Write the failing API test** (append to `tests/test_api.py`)

```python
def test_gaps_endpoint_sector_filter(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    # seed row c2 (contract_no_payment) is sector 71, so sector=45 -> empty
    resp = client.get("/api/gaps?type=contract_no_payment&sector=45")
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 6: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_api.py::test_gaps_endpoint_sector_filter -v`
Expected: FAIL (endpoint ignores sector).

- [ ] **Step 7: Replace the gaps endpoint in `api/app.py`** with:

```python
@app.get("/api/gaps")
def get_gaps(gap_type: str = Query("contract_no_payment", alias="type"),
             sector: str | None = None, region: str | None = None):
    return queries.gaps(config.OUT_DIR, gap_type=gap_type, sector=sector, region=region)
```

- [ ] **Step 8: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/recovery/queries.py api/app.py tests/test_queries.py tests/test_api.py
git commit -m "feat: gaps sector/region filters + supplier_edrpou for drill-down"
```

---

### Task 5: Frontend shell + styles

**Files:**
- Rewrite: `web/index.html`
- Create: `web/styles.css`

- [ ] **Step 1: Write `web/styles.css`**

```css
:root {
  --bg: #f8fafc; --card: #fff; --ink: #0f172a; --muted: #64748b;
  --line: #e2e8f0; --accent: #2563eb;
  --full: #15803d; --noted: #6b7280; --break: #b91c1c;
}
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; margin: 0; background: var(--bg); color: var(--ink); }
header {
  position: sticky; top: 0; z-index: 10; background: var(--card);
  border-bottom: 1px solid var(--line); padding: .75rem 1.25rem;
}
header h1 { font-size: 1.1rem; margin: 0 0 .25rem; }
header p { margin: 0 0 .5rem; color: var(--muted); font-size: .8rem; }
.filters { display: flex; gap: .75rem; flex-wrap: wrap; }
.filters label { font-size: .8rem; color: var(--muted); display: flex; gap: .35rem; align-items: center; }
select { padding: .35rem .5rem; border: 1px solid var(--line); border-radius: .4rem; background: #fff; }
main { max-width: 1100px; margin: 0 auto; padding: 1.25rem; display: grid; gap: 1.25rem; }
section { background: var(--card); border: 1px solid var(--line); border-radius: .6rem; padding: 1rem 1.25rem; }
section h2 { font-size: .95rem; margin: 0 0 .75rem; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: .75rem; background: none; border: 0; padding: 0; }
.kpi { background: var(--card); border: 1px solid var(--line); border-radius: .6rem; padding: .75rem 1rem; }
.kpi .label { font-size: .75rem; color: var(--muted); }
.kpi .value { font-size: 1.35rem; font-weight: 600; }
.kpi.break .value { color: var(--break); }
.kpi .sub { font-size: .72rem; color: var(--muted); margin-top: .15rem; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; }
.bar-row { display: grid; grid-template-columns: 160px 1fr 90px; align-items: center; gap: .5rem; margin: .3rem 0; font-size: .82rem; }
.bar-track { background: #eef2f7; border-radius: .4rem; height: 16px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: .4rem; }
.bar-fill.full { background: var(--full); }
.bar-fill.payment_no_ted { background: var(--noted); }
.bar-fill.contract_no_payment { background: var(--break); }
.bar-fill.funnel { background: var(--accent); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
svg#sankey { width: 100%; height: 320px; display: block; }
table { border-collapse: collapse; width: 100%; }
th, td { border-bottom: 1px solid var(--line); padding: .4rem .5rem; font-size: .85rem; text-align: left; }
th { cursor: pointer; user-select: none; color: var(--muted); font-weight: 600; }
th.num, td.num { text-align: right; }
tbody tr { cursor: pointer; }
tbody tr:hover { background: #f1f5f9; }
.tag { font-size: .68rem; padding: .05rem .35rem; border-radius: .3rem; background: #fef3c7; color: #92400e; margin-left: .35rem; }
.skeleton { background: linear-gradient(90deg,#eef2f7 25%,#e2e8f0 50%,#eef2f7 75%); background-size: 200% 100%; animation: sk 1.2s infinite; border-radius: .4rem; min-height: 1rem; }
@keyframes sk { from { background-position: 200% 0; } to { background-position: -200% 0; } }
.empty, .error { color: var(--muted); font-size: .85rem; padding: .5rem 0; }
.error { color: var(--break); }
.modal-backdrop { position: fixed; inset: 0; background: rgba(15,23,42,.45); display: none; align-items: center; justify-content: center; z-index: 50; }
.modal-backdrop.open { display: flex; }
.modal { background: #fff; border-radius: .6rem; padding: 1.25rem; max-width: 640px; width: 92%; max-height: 80vh; overflow: auto; }
.modal h3 { margin: 0 0 .5rem; }
.modal .close { float: right; cursor: pointer; border: 0; background: none; font-size: 1.2rem; color: var(--muted); }
@media (max-width: 720px) {
  .kpis { grid-template-columns: repeat(2, 1fr); }
  .two-col { grid-template-columns: 1fr; }
  .bar-row { grid-template-columns: 110px 1fr 70px; }
}
```

- [ ] **Step 2: Rewrite `web/index.html`**

```html
<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Гроші на відбудову України</title>
  <link rel="stylesheet" href="/static/styles.css" />
  <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
  <script src="https://cdn.jsdelivr.net/npm/d3-sankey@0.12"></script>
</head>
<body>
  <header>
    <h1>Наскрізний слід грошей на відбудову України</h1>
    <p>ProZorro → казначейські виплати (ядро) + TED overlay. Дані: разовий знімок, останні 12 міс.</p>
    <div class="filters">
      <label>Сектор CPV:
        <select id="sector">
          <option value="">усі</option>
          <option value="45">45 — будівництво</option>
          <option value="71">71 — інженерія</option>
          <option value="09">09 — енергетика</option>
          <option value="31">31 — електрообладнання</option>
          <option value="34">34 — транспорт</option>
        </select>
      </label>
      <label>Регіон:
        <select id="region"><option value="">усі</option></select>
      </label>
    </div>
  </header>

  <main>
    <div class="kpis" id="kpi"></div>

    <div class="two-col">
      <section><h2>Feasibility-воронка</h2><div id="funnel"></div></section>
      <section><h2>Розбивка за станами</h2><div id="state-bars"></div></section>
    </div>

    <section>
      <h2>Фінансовий слід (Sankey)</h2>
      <svg id="sankey"></svg>
      <div class="empty" id="sankey-note"></div>
    </section>

    <div class="two-col">
      <section><h2>Топ-виконавці</h2><div id="top-suppliers"></div></section>
      <section><h2>Топ-регіони</h2><div id="top-regions"></div></section>
    </div>

    <section>
      <h2>Обриви ланцюга (контракт без виплати)</h2>
      <table id="gaps">
        <thead><tr>
          <th data-key="contract_id">Контракт</th>
          <th data-key="supplier_name">Виконавець</th>
          <th data-key="cpv_div">CPV</th>
          <th data-key="region">Регіон</th>
          <th data-key="contract_amount_uah" class="num">Сума, грн</th>
        </tr></thead>
        <tbody></tbody>
      </table>
      <div class="empty" id="gaps-empty"></div>
    </section>
  </main>

  <div class="modal-backdrop" id="modal-backdrop">
    <div class="modal" id="modal">
      <button class="close" id="modal-close" aria-label="Закрити">×</button>
      <div id="modal-body"></div>
    </div>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Verify serving (synthetic seed)**

Run (PowerShell), from repo root:
```
.venv/Scripts/python scripts/seed_demo.py
Start-Process -NoNewWindow .venv/Scripts/python -ArgumentList "-m","uvicorn","api.app:app","--port","8131"
```
Then with `.venv/Scripts/python` + httpx, GET `http://127.0.0.1:8131/` (expect 200, body contains `Наскрізний слід`), GET `/static/styles.css` (expect 200, `text/css`), GET `/static/app.js` (expect 404 for now — app.js not created yet; that's fine this task). Stop the server.

Expected: `/` and `/static/styles.css` return 200; the page references `/static/app.js`.

- [ ] **Step 4: Commit**

```bash
git add web/index.html web/styles.css
git commit -m "feat: responsive dashboard shell + styles (sticky filters, sections, modal)"
```

---

### Task 6: Frontend app logic (`web/app.js`)

**Files:**
- Create: `web/app.js`

This is the whole client: state, fetch, per-section render, interactions. It is one file
with one responsibility (the dashboard app), built from small functions.

- [ ] **Step 1: Write `web/app.js`**

```javascript
"use strict";

const esc = (s) => (s ?? "").toString()
  .replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const fmt = (n) => new Intl.NumberFormat("uk-UA").format(Math.round(n ?? 0));
const pct = (a, b) => (b > 0 ? Math.round((a / b) * 100) : 0);

const state = { sector: "", region: "", gaps: [], gapSort: { key: "contract_amount_uah", dir: -1 } };

function q() {
  const p = new URLSearchParams();
  if (state.sector) p.set("sector", state.sector);
  if (state.region) p.set("region", state.region);
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function skeleton(el, lines = 3) {
  el.innerHTML = Array.from({ length: lines })
    .map(() => `<div class="skeleton" style="height:1.2rem;margin:.3rem 0"></div>`).join("");
}

// ---- section renderers ----

function renderKpi(k) {
  const el = document.getElementById("kpi");
  const share = pct(k.paid_uah, k.contracted_uah);
  el.innerHTML = `
    <div class="kpi"><div class="label">Оголошено (TED), €</div>
      <div class="value">${fmt(k.announced_eur)}</div></div>
    <div class="kpi"><div class="label">Законтрактовано, грн</div>
      <div class="value">${fmt(k.contracted_uah)}</div></div>
    <div class="kpi"><div class="label">Виплачено, грн</div>
      <div class="value">${fmt(k.paid_uah)}</div>
      <div class="sub">${share}% від законтрактованого</div></div>
    <div class="kpi break"><div class="label">Обриви (контракт без виплати)</div>
      <div class="value">${fmt(k.breaks)}</div></div>`;
}

function bar(label, value, max, cls, right) {
  const w = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return `<div class="bar-row"><span>${esc(label)}</span>
    <span class="bar-track"><span class="bar-fill ${cls}" style="width:${w}%"></span></span>
    <span class="num">${esc(right)}</span></div>`;
}

function renderFunnel(rows) {
  const el = document.getElementById("funnel");
  if (!rows.length) { el.innerHTML = `<div class="empty">Немає даних.</div>`; return; }
  const labels = { contracts: "Контракти", with_payment: "З виплатами", with_ted_overlay: "З TED" };
  const max = Math.max(...rows.map((r) => r.count), 1);
  el.innerHTML = rows.map((r) =>
    bar(labels[r.step] ?? r.step, r.count, max, "funnel", fmt(r.count))).join("");
}

function renderStateBars(rows) {
  const el = document.getElementById("state-bars");
  if (!rows.length) { el.innerHTML = `<div class="empty">Немає даних.</div>`; return; }
  const labels = {
    full: "Повний ланцюг", payment_no_ted: "Виплата без TED",
    contract_no_payment: "Контракт без виплати",
  };
  const max = Math.max(...rows.map((r) => r.count), 1);
  el.innerHTML = rows.map((r) =>
    bar(labels[r.state] ?? r.state, r.count, max, r.state, `${r.count} · ${fmt(r.contracted_uah)} грн`))
    .join("");
}

function renderSankey(data) {
  const svg = d3.select("#sankey");
  svg.selectAll("*").remove();
  const note = document.getElementById("sankey-note");
  note.textContent = data.announced_eur
    ? `Ліва частина (TED) показана для довідки: оголошено €${fmt(data.announced_eur)}. Потік масштабується в грн.`
    : "TED-сторона порожня для цього зрізу — типово для бюджетної підтримки (див. README).";
  const total = (data.links || []).reduce((s, l) => s + l.value, 0);
  if (!total) { return; }
  const width = document.getElementById("sankey").clientWidth || 880;
  const height = 320;
  const { nodes, links } = d3.sankey()
    .nodeWidth(18).nodePadding(20)
    .extent([[1, 1], [width - 1, height - 20]])({
      nodes: data.nodes.map((d) => ({ ...d })),
      links: data.links.map((d) => ({ ...d })),
    });
  svg.attr("viewBox", `0 0 ${width} ${height}`);
  svg.append("g").selectAll("rect").data(nodes).join("rect")
    .attr("x", (d) => d.x0).attr("y", (d) => d.y0)
    .attr("height", (d) => Math.max(1, d.y1 - d.y0))
    .attr("width", (d) => d.x1 - d.x0).attr("fill", "#2563eb")
    .append("title").text((d) => d.name);
  svg.append("g").attr("fill", "none").selectAll("path").data(links).join("path")
    .attr("d", d3.sankeyLinkHorizontal())
    .attr("stroke", "#93c5fd").attr("stroke-width", (d) => Math.max(1, d.width))
    .attr("opacity", .6)
    .append("title").text((d) => `${fmt(d.value)} грн`);
  svg.append("g").selectAll("text").data(nodes).join("text")
    .attr("x", (d) => (d.x0 < width / 2 ? d.x1 + 6 : d.x0 - 6))
    .attr("y", (d) => (d.y1 + d.y0) / 2).attr("dy", "0.35em")
    .attr("text-anchor", (d) => (d.x0 < width / 2 ? "start" : "end"))
    .text((d) => d.name).style("font-size", "12px");
}

function renderTopSuppliers(rows) {
  const el = document.getElementById("top-suppliers");
  if (!rows.length) { el.innerHTML = `<div class="empty">Немає даних.</div>`; return; }
  el.innerHTML = `<table><tbody>${rows.map((r) => `<tr data-edrpou="${esc(r.edrpou)}">
    <td>${esc(r.supplier_name)}</td>
    <td class="num">${fmt(r.contracted_uah)} грн</td></tr>`).join("")}</tbody></table>`;
  el.querySelectorAll("tr[data-edrpou]").forEach((tr) =>
    tr.addEventListener("click", () => openSupplier(tr.dataset.edrpou)));
}

function renderTopRegions(rows) {
  const el = document.getElementById("top-regions");
  if (!rows.length) { el.innerHTML = `<div class="empty">Немає даних.</div>`; return; }
  el.innerHTML = `<table><tbody>${rows.map((r) => `<tr>
    <td>${esc(r.region)}</td>
    <td class="num">${fmt(r.contracted_uah)} грн</td></tr>`).join("")}</tbody></table>`;
}

function renderGaps(rows) {
  state.gaps = rows;
  const tbody = document.querySelector("#gaps tbody");
  const empty = document.getElementById("gaps-empty");
  if (!rows.length) {
    tbody.innerHTML = "";
    empty.textContent = "Обривів немає для цього зрізу.";
    return;
  }
  empty.textContent = "";
  const { key, dir } = state.gapSort;
  const sorted = [...rows].sort((a, b) => {
    const av = a[key], bv = b[key];
    if (typeof av === "number") return (av - bv) * dir;
    return String(av ?? "").localeCompare(String(bv ?? "")) * dir;
  });
  tbody.innerHTML = sorted.map((g) => `<tr data-edrpou="${esc(g.supplier_edrpou)}">
    <td>${esc(g.contract_id)}</td><td>${esc(g.supplier_name)}</td>
    <td>${esc(g.cpv_div)}</td><td>${esc(g.region)}</td>
    <td class="num">${fmt(g.contract_amount_uah)}</td></tr>`).join("");
  tbody.querySelectorAll("tr[data-edrpou]").forEach((tr) =>
    tr.addEventListener("click", () => openSupplier(tr.dataset.edrpou)));
}

async function openSupplier(edrpou) {
  if (!edrpou) return;
  const body = document.getElementById("modal-body");
  body.innerHTML = `<div class="skeleton" style="height:6rem"></div>`;
  document.getElementById("modal-backdrop").classList.add("open");
  try {
    const d = await getJSON(`/api/supplier/${encodeURIComponent(edrpou)}`);
    const rows = (d.contracts || []).map((c) => `<tr>
      <td>${esc(c.contract_id)}</td><td>${esc(c.cpv_div)}</td><td>${esc(c.region)}</td>
      <td class="num">${fmt(c.contract_amount_uah)}</td>
      <td class="num">${fmt(c.paid_amount_uah)}</td>
      <td>${c.ted_id ? esc(c.ted_id) + '<span class="tag">слабкий TED-збіг</span>' : "—"}</td>
      <td>${esc(c.state)}</td></tr>`).join("");
    body.innerHTML = `<h3>Виконавець ЄДРПОУ ${esc(edrpou)}</h3>
      <table><thead><tr><th>Контракт</th><th>CPV</th><th>Регіон</th>
        <th class="num">Контракт, грн</th><th class="num">Виплачено, грн</th>
        <th>TED</th><th>Стан</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="7" class="empty">Немає контрактів.</td></tr>'}</tbody></table>`;
  } catch (e) {
    body.innerHTML = `<div class="error">Не вдалося завантажити: ${esc(e.message)}</div>`;
  }
}

// ---- orchestration ----

async function refresh() {
  ["funnel", "state-bars", "top-suppliers", "top-regions"].forEach((id) =>
    skeleton(document.getElementById(id)));
  try {
    const qs = q();
    const [kpi, funnel, brk, sankey, sup, reg, gaps] = await Promise.all([
      getJSON(`/api/kpi${qs}`),
      getJSON(`/api/funnel`),
      getJSON(`/api/breakdown${qs}`),
      getJSON(`/api/sankey${qs}`),
      getJSON(`/api/top?by=supplier${qs ? "&" + qs.slice(1) : ""}`),
      getJSON(`/api/top?by=region${qs ? "&" + qs.slice(1) : ""}`),
      getJSON(`/api/gaps?type=contract_no_payment${qs ? "&" + qs.slice(1) : ""}`),
    ]);
    renderKpi(kpi);
    renderFunnel(funnel);
    renderStateBars(brk);
    renderSankey(sankey);
    renderTopSuppliers(sup);
    renderTopRegions(reg);
    renderGaps(gaps);
  } catch (e) {
    document.getElementById("kpi").innerHTML =
      `<div class="kpi break"><div class="label">Помилка</div>
       <div class="value" style="font-size:.95rem">Дані ще не згенеровано — запустіть пайплайн (python run.py) або scripts/seed_demo.py</div></div>`;
    console.error(e);
  }
}

async function initRegions() {
  try {
    const regions = await getJSON("/api/regions");
    const sel = document.getElementById("region");
    regions.forEach((r) => {
      const o = document.createElement("option");
      o.value = r; o.textContent = r; sel.appendChild(o);
    });
  } catch (e) { console.error(e); }
}

function wire() {
  const onFilter = debounce(refresh, 150);
  document.getElementById("sector").addEventListener("change", (e) => {
    state.sector = e.target.value; onFilter();
  });
  document.getElementById("region").addEventListener("change", (e) => {
    state.region = e.target.value; onFilter();
  });
  document.querySelectorAll("#gaps th[data-key]").forEach((th) =>
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      state.gapSort = { key, dir: state.gapSort.key === key ? -state.gapSort.dir : -1 };
      renderGaps(state.gaps);
    }));
  const close = () => document.getElementById("modal-backdrop").classList.remove("open");
  document.getElementById("modal-close").addEventListener("click", close);
  document.getElementById("modal-backdrop").addEventListener("click", (e) => {
    if (e.target.id === "modal-backdrop") close();
  });
  let rt;
  new ResizeObserver(() => {
    clearTimeout(rt);
    rt = setTimeout(() => getJSON(`/api/sankey${q()}`).then(renderSankey).catch(() => {}), 120);
  }).observe(document.getElementById("sankey"));
}

initRegions();
wire();
refresh();
```

- [ ] **Step 2: Verify serving end to end (synthetic seed)**

From repo root (PowerShell):
```
.venv/Scripts/python scripts/seed_demo.py
Start-Process -NoNewWindow .venv/Scripts/python -ArgumentList "-m","uvicorn","api.app:app","--port","8132"
```
With `.venv/Scripts/python` + httpx, verify:
- `GET /` → 200, body contains `Наскрізний слід`.
- `GET /static/app.js` → 200, `application/javascript` (or `text/javascript`), body contains `function refresh`.
- `GET /api/regions` → 200, JSON array (the 7 demo regions, e.g. contains `Київська область`).
- `GET /api/breakdown` → 200, contains states `full`/`contract_no_payment`/`payment_no_ted`.
- `GET /api/top?by=supplier` → 200, first row has the largest `contracted_uah`.
- `GET /api/gaps?type=contract_no_payment` → 200, rows include `supplier_edrpou`.
Stop the server. (Visual rendering — Sankey, bars, modal — is confirmed in a browser; cannot be asserted headlessly.)

- [ ] **Step 3: Run the full backend suite (no regressions)**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add web/app.js
git commit -m "feat: dashboard app.js (filters, funnel, state bars, fluid sankey, top, sortable gaps, supplier modal)"
```

---

### Task 7: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update `README.md`**

Read the current `README.md`, then:
- Add a **Dashboard** section describing the single-scroll layout: sticky sector+region
  filters (combined), KPI band (with % paid), feasibility funnel, state breakdown bars,
  fluid Sankey, top suppliers/regions, sortable gaps table, and the click-through supplier
  modal. Note it is a no-build static bundle (`web/index.html` + `web/styles.css` +
  `web/app.js`) served by FastAPI.
- Update the **API endpoints** table to add: `GET /api/regions`, `GET /api/breakdown?sector=&region=`,
  `GET /api/top?by=supplier|region&sector=&region=&limit=`, and the extended
  `GET /api/gaps?type=&sector=&region=` (now returns `supplier_edrpou` for drill-down).
- Add a one-line quickstart note: without a live pull, run `python scripts/seed_demo.py`
  to populate `data/out/`, then `uvicorn api.app:app` and open http://127.0.0.1:8000/.
- Keep the existing pitch, stage table, data-contract, and honesty sections accurate.
Write it in clear English.

- [ ] **Step 2: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document the dashboard UI and new API endpoints"
```

---

## Self-Review

**Spec coverage:**
- Single-scroll responsive layout, sticky filters → Task 5 (index.html + styles.css). ✓
- Combined sector+region filters applied to KPI/Sankey/breakdown/top/gaps → Tasks 1-4 (backend filters) + Task 6 (`q()` applied to all fetches). ✓
- Feasibility funnel → Task 6 `renderFunnel` (uses existing `/api/funnel`). ✓
- State breakdown → Task 2 `breakdown` + Task 6 `renderStateBars`. ✓
- Top suppliers + top regions → Task 3 `top` + Task 6 `renderTopSuppliers`/`renderTopRegions`. ✓
- Supplier detail modal (click row/node) → Task 4 (`supplier_edrpou` in gaps) + Task 6 `openSupplier`. ✓
- Region dropdown populated → Task 1 `regions` + Task 6 `initRegions`. ✓
- Context: % paid, weak-TED note, tooltips, sankey note → Task 6 (`renderKpi` share, modal tag, `<title>` tooltips, `sankey-note`). ✓
- Fluid Sankey (ResizeObserver) → Task 6 `renderSankey` + `wire()` observer. ✓
- Fast feedback: skeletons, debounce, in-place updates, error/empty states → Task 6. ✓
- Sortable gaps table → Task 6 `renderGaps` + `wire()` header clicks. ✓
- State colors green/grey/red → Task 5 styles.css. ✓
- No build step, vanilla + d3 CDN, 3 static files → Tasks 5-6. ✓
- `by` allowlist (no SQL injection) → Task 3 (`top` ValueError + endpoint `Literal`). ✓
- README in English → Task 7. ✓
- Backend TDD; frontend serving verification → all tasks. ✓

**Out-of-scope confirmed absent:** geo map, CSV export, gaps_*.parquet/orphan-spending,
build step/framework, live-ingest API fixes. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code. The only prose-described
step is Task 7 (README), which is documentation, not code — acceptable.

**Type/name consistency:** `breakdown` returns `{state,count,contracted_uah,paid_uah}` (Task 2)
— consumed by `renderStateBars` (Task 6) using exactly those keys. `top by=supplier` returns
`{edrpou,supplier_name,contracted_uah,paid_uah,contracts}` — `renderTopSuppliers` uses
`edrpou,supplier_name,contracted_uah`. `top by=region` returns `{region,contracted_uah,...}`
— `renderTopRegions` uses `region,contracted_uah`. `gaps` returns `supplier_edrpou` (Task 4)
— `renderGaps`/`openSupplier` use it. `/api/top` query-string assembly in `refresh()` appends
`&sector=..&region=..` after `by=...` — consistent with the endpoint's params. ✓
