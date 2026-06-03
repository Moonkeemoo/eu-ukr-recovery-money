# eu-ukr-recovery-money Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Sankey financial-trail product tracing reconstruction money from EU tenders (TED, overlay) through Ukrainian procurement (ProZorro) to treasury payments (spending.gov.ua), surfacing who gets paid and where the chain breaks.

**Architecture:** A linear Python pipeline of re-runnable stages, each writing a Parquet artifact and logging unresolved rows as honest gaps. The core join is `ProZorro winner EDRPOU = spending recipient EDRPOU`; TED is a confidence-tagged overlay matched by normalized company name + CPV category. DuckDB queries the Parquet artifacts; FastAPI serves Sankey/KPI/detail JSON; a thin vanilla-JS + d3-sankey page renders the UI (Ukrainian).

**Tech Stack:** Python 3.11+, `httpx` (API clients), `polars` (normalize/join, writes Parquet), `duckdb` (query layer), `fastapi` + `uvicorn` (serving), `pytest` + `respx` (tests), vanilla JS + `d3-sankey` (CDN).

---

## File Structure

```
eu-ukr-recovery-money/
├── pyproject.toml                  # deps, ruff, pytest config
├── run.py                          # orchestrates stages 1-4
├── src/recovery/
│   ├── __init__.py
│   ├── config.py                   # CPV prefixes, time window, paths, API hosts
│   ├── normalize_fields.py         # pure: EDRPOU, company-name, CPV-category normalizers
│   ├── clients.py                  # httpx clients for the 3 APIs + on-disk cache
│   ├── stage1_ingest.py            # pull + cache raw responses
│   ├── stage2_normalize.py         # raw -> normalized Parquet tables
│   ├── stage3_join.py              # core EDRPOU join + TED overlay
│   ├── stage4_chain.py             # chain records + state tags + funnel
│   └── queries.py                  # DuckDB queries over Parquet (sankey/kpi/supplier/gaps/funnel)
├── api/
│   └── app.py                      # FastAPI app importing queries.py
├── web/
│   └── index.html                  # d3-sankey + KPI band + filters (Ukrainian)
├── tests/
│   ├── fixtures/                   # saved raw API JSON snippets
│   ├── test_normalize_fields.py
│   ├── test_clients_cache.py
│   ├── test_stage2_normalize.py
│   ├── test_stage3_join.py
│   ├── test_stage4_chain.py
│   ├── test_queries.py
│   └── test_api.py
├── data/cache/   data/out/         # gitignored
└── docs/superpowers/{specs,plans}/
```

Data contract between stages (Parquet schemas):

- `data/out/prozorro_contracts.parquet`: `contract_id, cpv, cpv_div, supplier_edrpou, supplier_name, supplier_name_norm, amount_uah, region, redacted(bool)`
- `data/out/spending_tx.parquet`: `tx_id, recipient_edrpou, recipient_name, recipient_name_norm, amount_uah, payment_date, purpose`
- `data/out/ted_notices.parquet`: `ted_id, cpv, cpv_div, winner_name, winner_name_norm, winner_country, amount_eur, region`
- `data/out/chain.parquet`: `edrpou, supplier_name, cpv_div, region, ted_id(nullable), contract_id(nullable), contract_amount_uah, paid_amount_uah, ted_amount_eur(nullable), ted_match_confidence(nullable), state` where `state ∈ {full, contract_no_payment, payment_no_ted, payment_no_contract}`
- `data/out/gaps_*.parquet`: unresolved rows per stage (free-form + a `reason` column)
- `data/out/funnel.parquet`: `step(str), count(int)`

---

### Task 0: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/recovery/__init__.py` (empty)
- Create: `src/recovery/config.py`
- Test: `tests/test_config_smoke.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "recovery"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "polars>=1.0",
    "duckdb>=1.0",
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "pyarrow>=16.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "respx>=0.21", "ruff>=0.5"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 2: Write `src/recovery/config.py`**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "cache"
OUT_DIR = ROOT / "data" / "out"

# Extended reconstruction CPV divisions (first 2 digits of the CPV code).
CPV_DIVISIONS = ("45", "71", "09", "31", "34")

# 12-month window, end is the snapshot date. Override END_DATE in tests.
WINDOW_MONTHS = 12

# API hosts (all unauthenticated for reading).
PROZORRO_OCDS = "https://public-api.prozorro.gov.ua/api/2.5"
SPENDING_API = "https://api.spending.gov.ua/api"
TED_SEARCH = "https://api.ted.europa.eu/v3/notices/search"


def cpv_in_scope(cpv: str | None) -> bool:
    """True if a CPV code belongs to a reconstruction division."""
    if not cpv:
        return False
    return cpv[:2] in CPV_DIVISIONS
```

- [ ] **Step 3: Write `tests/test_config_smoke.py`**

```python
from recovery import config


def test_cpv_in_scope():
    assert config.cpv_in_scope("45233140-2") is True   # roadworks
    assert config.cpv_in_scope("71322000-1") is True    # engineering
    assert config.cpv_in_scope("15800000-6") is False   # food
    assert config.cpv_in_scope(None) is False
    assert config.cpv_in_scope("") is False


def test_paths_exist_as_config():
    assert config.CPV_DIVISIONS == ("45", "71", "09", "31", "34")
    assert str(config.OUT_DIR).endswith("out")
```

- [ ] **Step 4: Create venv and install**

Run: `python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"`
Expected: installs without error (Windows path shown; on POSIX use `.venv/bin/python`).

- [ ] **Step 5: Run the smoke test**

Run: `.venv/Scripts/python -m pytest tests/test_config_smoke.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/recovery/__init__.py src/recovery/config.py tests/test_config_smoke.py
git commit -m "chore: scaffold project (pyproject, config, smoke test)"
```

---

### Task 1: Field normalizers (pure functions)

**Files:**
- Create: `src/recovery/normalize_fields.py`
- Test: `tests/test_normalize_fields.py`

- [ ] **Step 1: Write the failing tests**

```python
from recovery.normalize_fields import normalize_edrpou, normalize_company_name, cpv_division


def test_normalize_edrpou_pads_and_strips():
    assert normalize_edrpou("31725604") == "31725604"
    assert normalize_edrpou(" 31725604 ") == "31725604"
    assert normalize_edrpou("1234567") == "01234567"     # pad to 8
    assert normalize_edrpou("UA-31725604") == "31725604" # strip non-digits
    assert normalize_edrpou(None) is None
    assert normalize_edrpou("") is None
    assert normalize_edrpou("not-a-code") is None


def test_normalize_company_name():
    # lowercase, strip legal forms and quotes/punctuation, collapse whitespace
    assert normalize_company_name('ТОВ "ІТ СПЕЦІАЛІСТ"') == "іт спеціаліст"
    assert normalize_company_name("LLC  Build  Co.") == "build co"
    assert normalize_company_name('Приватне підприємство «Шлях»') == "шлях"
    assert normalize_company_name(None) == ""


def test_cpv_division():
    assert cpv_division("45233140-2") == "45"
    assert cpv_division("09310000") == "09"
    assert cpv_division(None) is None
    assert cpv_division("4") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_normalize_fields.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recovery.normalize_fields'`.

- [ ] **Step 3: Implement `src/recovery/normalize_fields.py`**

```python
import re

_LEGAL_FORMS = (
    "товариство з обмеженою відповідальністю", "приватне підприємство",
    "тов", "пп", "фоп", "дп", "ат", "пат", "прат",
    "llc", "ltd", "inc", "gmbh", "sa", "spa", "co",
)
_NONWORD = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_edrpou(value: str | None) -> str | None:
    """Canonical 8-digit EDRPOU, or None if no digits found."""
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    return digits.zfill(8) if len(digits) < 8 else digits


def normalize_company_name(value: str | None) -> str:
    """Lowercase, strip punctuation and leading/standalone legal forms."""
    if not value:
        return ""
    text = _NONWORD.sub(" ", value.lower())
    tokens = [t for t in _WS.split(text) if t and t not in _LEGAL_FORMS]
    return " ".join(tokens).strip()


def cpv_division(cpv: str | None) -> str | None:
    """First two digits of a CPV code, or None."""
    if not cpv or len(cpv) < 2 or not cpv[:2].isdigit():
        return None
    return cpv[:2]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_normalize_fields.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/recovery/normalize_fields.py tests/test_normalize_fields.py
git commit -m "feat: field normalizers (EDRPOU, company name, CPV division)"
```

---

### Task 2: Cached HTTP client

**Files:**
- Create: `src/recovery/clients.py`
- Test: `tests/test_clients_cache.py`

- [ ] **Step 1: Write the failing test**

```python
import httpx
import respx
from recovery.clients import CachedClient


@respx.mock
def test_get_json_caches_to_disk(tmp_path):
    route = respx.get("https://example.test/data").mock(
        return_value=httpx.Response(200, json={"ok": 1})
    )
    client = CachedClient(cache_dir=tmp_path)

    first = client.get_json("https://example.test/data", params={"a": "1"})
    second = client.get_json("https://example.test/data", params={"a": "1"})

    assert first == {"ok": 1}
    assert second == {"ok": 1}
    # second call served from disk cache, network hit only once
    assert route.call_count == 1
    assert any(tmp_path.iterdir())
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_clients_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recovery.clients'`.

- [ ] **Step 3: Implement `src/recovery/clients.py`**

```python
import hashlib
import json
import time
from pathlib import Path

import httpx


class CachedClient:
    """Thin httpx wrapper: GET/POST JSON with on-disk caching and retry/backoff."""

    def __init__(self, cache_dir: Path, max_retries: int = 3):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=30.0)

    def _key(self, method: str, url: str, params, body) -> Path:
        raw = json.dumps([method, url, params, body], sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{digest}.json"

    def _request(self, method: str, url: str, params=None, json_body=None) -> dict:
        path = self._key(method, url, params, json_body)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.request(method, url, params=params, json=json_body)
                resp.raise_for_status()
                data = resp.json()
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                return data
            except httpx.HTTPError as exc:
                last_exc = exc
                time.sleep(0.5 * (2 ** attempt))
        raise last_exc

    def get_json(self, url: str, params=None) -> dict:
        return self._request("GET", url, params=params)

    def post_json(self, url: str, json_body: dict) -> dict:
        return self._request("POST", url, json_body=json_body)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_clients_cache.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/recovery/clients.py tests/test_clients_cache.py
git commit -m "feat: cached HTTP client with retry/backoff"
```

---

### Task 3: Stage 1 — ingest

**Files:**
- Create: `src/recovery/stage1_ingest.py`
- Create: `tests/fixtures/prozorro_page.json`, `tests/fixtures/spending_page.json`, `tests/fixtures/ted_page.json`
- Test: `tests/test_stage1_ingest.py`

Stage 1 pulls each API page-by-page through `CachedClient`, stops at the configured page cap, and returns lists of raw records. It does no normalization — that is Task 4. Keep per-API pull functions separate so each is independently testable.

- [ ] **Step 1: Create fixtures**

`tests/fixtures/prozorro_page.json`:
```json
{"data": [{"id": "ocds-1", "contractID": "UA-2025-09-01-000001",
  "procuringEntity": {"identifier": {"id": "31517060", "scheme": "UA-EDR"}},
  "suppliers": [{"name": "ТОВ \"Шлях\"", "identifier": {"id": "31725604", "scheme": "UA-EDR"}}],
  "value": {"amount": 1000000, "currency": "UAH"},
  "items": [{"classification": {"scheme": "CPV", "id": "45233140-2"},
             "deliveryAddress": {"region": "Київська область"}}]}]}
```

`tests/fixtures/spending_page.json`:
```json
{"items": [{"id": "tx-1", "recipt_edrpou": "31725604", "recipt_name": "ТОВ \"Шлях\"",
  "amount": 750000, "trans_date": "2025-10-15", "payment_details": "оплата за ремонт дороги"}]}
```

`tests/fixtures/ted_page.json`:
```json
{"notices": [{"publication-number": "00654321-2025",
  "classification-cpv": "45233140", "winner-name": "Bud Co LLC",
  "winner-country": "PL", "value": 500000, "place-of-performance": "UA"}],
  "totalNoticeCount": 1}
```

- [ ] **Step 2: Write the failing test**

```python
import json
from pathlib import Path

import httpx
import respx

from recovery.stage1_ingest import pull_prozorro, pull_spending, pull_ted

FIX = Path(__file__).parent / "fixtures"


@respx.mock
def test_pull_prozorro_returns_records(tmp_path):
    page = json.loads((FIX / "prozorro_page.json").read_text(encoding="utf-8"))
    respx.get(url__startswith="https://public-api.prozorro.gov.ua").mock(
        return_value=httpx.Response(200, json=page)
    )
    records = pull_prozorro(cache_dir=tmp_path, max_pages=1)
    assert len(records) == 1
    assert records[0]["contractID"] == "UA-2025-09-01-000001"


@respx.mock
def test_pull_spending_returns_records(tmp_path):
    page = json.loads((FIX / "spending_page.json").read_text(encoding="utf-8"))
    respx.get(url__startswith="https://api.spending.gov.ua").mock(
        return_value=httpx.Response(200, json=page)
    )
    records = pull_spending(cache_dir=tmp_path, edrpous=["31725604"], max_pages=1)
    assert records[0]["recipt_edrpou"] == "31725604"


@respx.mock
def test_pull_ted_returns_records(tmp_path):
    page = json.loads((FIX / "ted_page.json").read_text(encoding="utf-8"))
    respx.post(url__startswith="https://api.ted.europa.eu").mock(
        return_value=httpx.Response(200, json=page)
    )
    records = pull_ted(cache_dir=tmp_path, max_pages=1)
    assert records[0]["publication-number"] == "00654321-2025"
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_stage1_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recovery.stage1_ingest'`.

- [ ] **Step 4: Implement `src/recovery/stage1_ingest.py`**

```python
from pathlib import Path

from . import config
from .clients import CachedClient


def pull_prozorro(cache_dir: Path, max_pages: int = 50) -> list[dict]:
    """Pull ProZorro OCDS contracts, filtered to reconstruction CPVs."""
    client = CachedClient(cache_dir / "prozorro")
    out: list[dict] = []
    page = 0
    while page < max_pages:
        data = client.get_json(
            f"{config.PROZORRO_OCDS}/contracts",
            params={"opt_schema": "ocds", "page": page},
        )
        rows = data.get("data") or []
        if not rows:
            break
        for row in rows:
            items = row.get("items") or []
            if any(config.cpv_in_scope((it.get("classification") or {}).get("id")) for it in items):
                out.append(row)
        page += 1
        if len(rows) == 0:
            break
    return out


def pull_spending(cache_dir: Path, edrpous: list[str], max_pages: int = 50) -> list[dict]:
    """Pull spending transactions for the given recipient EDRPOUs."""
    client = CachedClient(cache_dir / "spending")
    out: list[dict] = []
    for edrpou in edrpous:
        page = 0
        while page < max_pages:
            data = client.get_json(
                f"{config.SPENDING_API}/v2/api/transactions",
                params={"recipt_edrpou": edrpou, "page": page},
            )
            rows = data.get("items") or data.get("transactions") or []
            if not rows:
                break
            out.extend(rows)
            page += 1
    return out


def pull_ted(cache_dir: Path, max_pages: int = 50) -> list[dict]:
    """Pull TED notices for reconstruction CPVs via the v3 search POST endpoint."""
    client = CachedClient(cache_dir / "ted")
    out: list[dict] = []
    cpv_expr = " OR ".join(f"classification-cpv={d}*" for d in config.CPV_DIVISIONS)
    page = 1
    while page <= max_pages:
        data = client.post_json(
            config.TED_SEARCH,
            {"query": cpv_expr, "page": page, "limit": 100},
        )
        rows = data.get("notices") or []
        if not rows:
            break
        out.extend(rows)
        page += 1
    return out
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_stage1_ingest.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/recovery/stage1_ingest.py tests/test_stage1_ingest.py tests/fixtures/
git commit -m "feat: stage 1 ingest (ProZorro, spending, TED pulls with fixtures)"
```

---

### Task 4: Stage 2 — normalize

**Files:**
- Create: `src/recovery/stage2_normalize.py`
- Test: `tests/test_stage2_normalize.py`

Stage 2 turns raw records (Task 3 fixtures) into three normalized Polars DataFrames matching the data contract. Pure transformation: input list[dict] → DataFrame.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_stage2_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/recovery/stage2_normalize.py`**

```python
import polars as pl

from .normalize_fields import cpv_division, normalize_company_name, normalize_edrpou


def normalize_prozorro(raw: list[dict]) -> pl.DataFrame:
    rows = []
    for r in raw:
        suppliers = r.get("suppliers") or [{}]
        sup = suppliers[0]
        items = r.get("items") or [{}]
        cpv = (items[0].get("classification") or {}).get("id")
        region = (items[0].get("deliveryAddress") or {}).get("region")
        rows.append({
            "contract_id": r.get("contractID") or r.get("id"),
            "cpv": cpv,
            "cpv_div": cpv_division(cpv),
            "supplier_edrpou": normalize_edrpou((sup.get("identifier") or {}).get("id")),
            "supplier_name": sup.get("name"),
            "supplier_name_norm": normalize_company_name(sup.get("name")),
            "amount_uah": (r.get("value") or {}).get("amount"),
            "region": region,
            "redacted": bool(r.get("redacted", False)),
        })
    return pl.DataFrame(rows)


def normalize_spending(raw: list[dict]) -> pl.DataFrame:
    rows = []
    for r in raw:
        name = r.get("recipt_name")
        rows.append({
            "tx_id": str(r.get("id")),
            "recipient_edrpou": normalize_edrpou(r.get("recipt_edrpou")),
            "recipient_name": name,
            "recipient_name_norm": normalize_company_name(name),
            "amount_uah": r.get("amount"),
            "payment_date": r.get("trans_date"),
            "purpose": r.get("payment_details"),
        })
    return pl.DataFrame(rows)


def normalize_ted(raw: list[dict]) -> pl.DataFrame:
    rows = []
    for r in raw:
        cpv = r.get("classification-cpv")
        name = r.get("winner-name")
        rows.append({
            "ted_id": r.get("publication-number"),
            "cpv": cpv,
            "cpv_div": cpv_division(cpv),
            "winner_name": name,
            "winner_name_norm": normalize_company_name(name),
            "winner_country": r.get("winner-country"),
            "amount_eur": r.get("value"),
            "region": r.get("place-of-performance"),
        })
    return pl.DataFrame(rows)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_stage2_normalize.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/recovery/stage2_normalize.py tests/test_stage2_normalize.py
git commit -m "feat: stage 2 normalize (ProZorro, spending, TED -> DataFrames)"
```

---

### Task 5: Stage 3 — join

**Files:**
- Create: `src/recovery/stage3_join.py`
- Test: `tests/test_stage3_join.py`

Core join: ProZorro contracts to spending on EDRPOU. TED overlay: attach a TED notice to a contract when `winner_name_norm` matches `supplier_name_norm` AND `cpv_div` matches; tag `ted_match_confidence` (1.0 exact name+cpv). Output an intermediate `joined` DataFrame: one row per contract, with aggregated paid amount and optional TED fields.

- [ ] **Step 1: Write the failing test**

```python
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
    ])
    ted = pl.DataFrame([
        {"ted_id": "t1", "winner_name_norm": "шлях", "cpv_div": "45", "amount_eur": 500000},
        {"ted_id": "t2", "winner_name_norm": "інша", "cpv_div": "45", "amount_eur": 100000},
    ])
    out = attach_ted_overlay(joined, ted)
    row = out.to_dicts()[0]
    assert row["ted_id"] == "t1"
    assert row["ted_match_confidence"] == 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_stage3_join.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/recovery/stage3_join.py`**

```python
import polars as pl


def join_core(contracts: pl.DataFrame, spending: pl.DataFrame) -> pl.DataFrame:
    """Left-join contracts to aggregated payments on EDRPOU. Missing pay = 0."""
    paid = (
        spending.group_by("recipient_edrpou")
        .agg(pl.col("amount_uah").sum().alias("paid_amount_uah"))
    )
    joined = contracts.join(
        paid, left_on="supplier_edrpou", right_on="recipient_edrpou", how="left"
    ).with_columns(
        pl.col("paid_amount_uah").fill_null(0),
        pl.col("amount_uah").alias("contract_amount_uah"),
    )
    return joined


def attach_ted_overlay(joined: pl.DataFrame, ted: pl.DataFrame) -> pl.DataFrame:
    """Attach a TED notice where winner_name_norm + cpv_div match. Confidence 1.0."""
    ted_keyed = ted.select(
        pl.col("winner_name_norm").alias("supplier_name_norm"),
        "cpv_div", "ted_id", "amount_eur",
    ).unique(subset=["supplier_name_norm", "cpv_div"], keep="first")
    out = joined.join(ted_keyed, on=["supplier_name_norm", "cpv_div"], how="left")
    out = out.with_columns(
        pl.when(pl.col("ted_id").is_not_null())
        .then(pl.lit(1.0))
        .otherwise(None)
        .alias("ted_match_confidence")
    )
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_stage3_join.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/recovery/stage3_join.py tests/test_stage3_join.py
git commit -m "feat: stage 3 join (core EDRPOU + TED overlay)"
```

---

### Task 6: Stage 4 — chain + funnel

**Files:**
- Create: `src/recovery/stage4_chain.py`
- Test: `tests/test_stage4_chain.py`

Stage 4 tags each joined row with a `state` and computes the feasibility funnel.

State rules:
- `full`: has contract AND paid > 0 AND ted_id present
- `contract_no_payment`: contract present, paid == 0
- `payment_no_ted`: contract present, paid > 0, ted_id null
- `payment_no_contract`: reserved (rows from spending with no matching contract — produced as a gap, not in `chain`)

- [ ] **Step 1: Write the failing test**

```python
import polars as pl

from recovery.stage4_chain import build_chain, build_funnel


def _joined():
    return pl.DataFrame([
        {"contract_id": "c1", "supplier_edrpou": "1", "supplier_name": "A",
         "cpv_div": "45", "region": "Київ", "contract_amount_uah": 1000000,
         "paid_amount_uah": 750000, "ted_id": "t1", "amount_eur": 500000,
         "ted_match_confidence": 1.0},
        {"contract_id": "c2", "supplier_edrpou": "2", "supplier_name": "B",
         "cpv_div": "45", "region": "Львів", "contract_amount_uah": 500000,
         "paid_amount_uah": 0, "ted_id": None, "amount_eur": None,
         "ted_match_confidence": None},
        {"contract_id": "c3", "supplier_edrpou": "3", "supplier_name": "C",
         "cpv_div": "71", "region": "Одеса", "contract_amount_uah": 200000,
         "paid_amount_uah": 200000, "ted_id": None, "amount_eur": None,
         "ted_match_confidence": None},
    ])


def test_build_chain_tags_state():
    chain = build_chain(_joined())
    state = {r["contract_id"]: r["state"] for r in chain.to_dicts()}
    assert state["c1"] == "full"
    assert state["c2"] == "contract_no_payment"
    assert state["c3"] == "payment_no_ted"


def test_build_funnel_counts():
    funnel = build_funnel(_joined())
    counts = {r["step"]: r["count"] for r in funnel.to_dicts()}
    assert counts["contracts"] == 3
    assert counts["with_payment"] == 2
    assert counts["with_ted_overlay"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_stage4_chain.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/recovery/stage4_chain.py`**

```python
import polars as pl


def build_chain(joined: pl.DataFrame) -> pl.DataFrame:
    state = (
        pl.when((pl.col("paid_amount_uah") > 0) & pl.col("ted_id").is_not_null())
        .then(pl.lit("full"))
        .when(pl.col("paid_amount_uah") == 0)
        .then(pl.lit("contract_no_payment"))
        .otherwise(pl.lit("payment_no_ted"))
    )
    return joined.with_columns(state.alias("state")).select(
        "contract_id", "supplier_edrpou", "supplier_name", "cpv_div", "region",
        "contract_amount_uah", "paid_amount_uah",
        pl.col("amount_eur").alias("ted_amount_eur"),
        "ted_id", "ted_match_confidence", "state",
    )


def build_funnel(joined: pl.DataFrame) -> pl.DataFrame:
    return pl.DataFrame([
        {"step": "contracts", "count": joined.height},
        {"step": "with_payment", "count": joined.filter(pl.col("paid_amount_uah") > 0).height},
        {"step": "with_ted_overlay", "count": joined.filter(pl.col("ted_id").is_not_null()).height},
    ])
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_stage4_chain.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/recovery/stage4_chain.py tests/test_stage4_chain.py
git commit -m "feat: stage 4 chain state tagging + feasibility funnel"
```

---

### Task 7: Orchestration (`run.py`)

**Files:**
- Create: `run.py`
- Test: `tests/test_run_smoke.py`

`run.py` wires stages 1→4 and writes Parquet artifacts to `data/out/`. It accepts `--max-pages` and a `--from-cache` flag so a re-run never re-hits the network. The test runs the full pipeline against the cached fixtures by monkeypatching the three pull functions.

- [ ] **Step 1: Write the failing test**

```python
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
        lambda **k: [{"publication-number": "t1", "classification-cpv": "45233140",
            "winner-name": "Шлях", "winner-country": "UA", "value": 500000,
            "place-of-performance": "UA"}])

    run_module.main(max_pages=1)

    chain = pl.read_parquet(Path(tmp_path) / "chain.parquet")
    assert chain.to_dicts()[0]["state"] == "full"
    assert (Path(tmp_path) / "funnel.parquet").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_run_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'run'`.

- [ ] **Step 3: Implement `run.py`**

```python
import argparse

from recovery import config
from recovery import stage1_ingest as stage1
from recovery.stage2_normalize import normalize_prozorro, normalize_spending, normalize_ted
from recovery.stage3_join import join_core, attach_ted_overlay
from recovery.stage4_chain import build_chain, build_funnel


def main(max_pages: int = 50) -> None:
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_pz = stage1.pull_prozorro(cache_dir=config.CACHE_DIR, max_pages=max_pages)
    contracts = normalize_prozorro(raw_pz)

    edrpous = [e for e in contracts["supplier_edrpou"].drop_nulls().unique().to_list()]
    raw_sp = stage1.pull_spending(cache_dir=config.CACHE_DIR, edrpous=edrpous, max_pages=max_pages)
    spending = normalize_spending(raw_sp)

    raw_ted = stage1.pull_ted(cache_dir=config.CACHE_DIR, max_pages=max_pages)
    ted = normalize_ted(raw_ted)

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
    parser.add_argument("--max-pages", type=int, default=50)
    args = parser.parse_args()
    main(max_pages=args.max_pages)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_run_smoke.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add run.py tests/test_run_smoke.py
git commit -m "feat: pipeline orchestration writing Parquet artifacts"
```

---

### Task 8: DuckDB query layer

**Files:**
- Create: `src/recovery/queries.py`
- Test: `tests/test_queries.py`

Queries read `chain.parquet` / `funnel.parquet` via DuckDB and return plain dicts/lists ready for JSON. Each query accepts optional `sector` (CPV div) and `region` filters.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/recovery/queries.py`**

```python
from pathlib import Path

import duckdb


def _conn(out_dir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE VIEW chain AS SELECT * FROM read_parquet(?)",
        [str(Path(out_dir) / "chain.parquet")],
    )
    return con


def _where(sector: str | None, region: str | None) -> tuple[str, list]:
    clauses, params = [], []
    if sector:
        clauses.append("cpv_div = ?")
        params.append(sector)
    if region:
        clauses.append("region = ?")
        params.append(region)
    return (("WHERE " + " AND ".join(clauses)) if clauses else ""), params


def kpi(out_dir: Path, sector: str | None = None, region: str | None = None) -> dict:
    con = _conn(out_dir)
    where, params = _where(sector, region)
    row = con.execute(
        f"""SELECT
              COALESCE(SUM(contract_amount_uah), 0) AS contracted,
              COALESCE(SUM(paid_amount_uah), 0) AS paid,
              COALESCE(SUM(ted_amount_eur), 0) AS announced_eur,
              SUM(CASE WHEN state = 'contract_no_payment' THEN 1 ELSE 0 END) AS breaks
            FROM chain {where}""",
        params,
    ).fetchone()
    return {
        "contracted_uah": int(row[0]), "paid_uah": int(row[1]),
        "announced_eur": int(row[2]), "breaks": int(row[3]),
    }


def sankey(out_dir: Path, sector: str | None = None, region: str | None = None) -> dict:
    con = _conn(out_dir)
    where, params = _where(sector, region)
    row = con.execute(
        f"""SELECT
              COALESCE(SUM(ted_amount_eur), 0),
              COALESCE(SUM(contract_amount_uah), 0),
              COALESCE(SUM(paid_amount_uah), 0)
            FROM chain {where}""",
        params,
    ).fetchone()
    nodes = [{"name": "Оголошено (TED)"}, {"name": "Законтрактовано"}, {"name": "Виплачено"}]
    links = [
        {"source": 0, "target": 1, "value": int(row[1])},
        {"source": 1, "target": 2, "value": int(row[2])},
    ]
    return {"nodes": nodes, "links": links, "announced_eur": int(row[0])}


def supplier(out_dir: Path, edrpou: str) -> dict:
    con = _conn(out_dir)
    rows = con.execute(
        "SELECT contract_id, cpv_div, region, contract_amount_uah, paid_amount_uah, "
        "ted_id, state FROM chain WHERE supplier_edrpou = ?",
        [edrpou],
    ).fetch_arrow_table().to_pylist()
    return {"edrpou": edrpou, "contracts": rows}


def gaps(out_dir: Path, gap_type: str = "contract_no_payment") -> list[dict]:
    con = _conn(out_dir)
    return con.execute(
        "SELECT contract_id, supplier_name, cpv_div, region, contract_amount_uah, state "
        "FROM chain WHERE state = ?",
        [gap_type],
    ).fetch_arrow_table().to_pylist()


def funnel(out_dir: Path) -> list[dict]:
    con = duckdb.connect(":memory:")
    return con.execute(
        "SELECT * FROM read_parquet(?)",
        [str(Path(out_dir) / "funnel.parquet")],
    ).fetch_arrow_table().to_pylist()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_queries.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/recovery/queries.py tests/test_queries.py
git commit -m "feat: DuckDB query layer (sankey, kpi, supplier, gaps, funnel)"
```

---

### Task 9: FastAPI app

**Files:**
- Create: `api/__init__.py` (empty)
- Create: `api/app.py`
- Test: `tests/test_api.py`

The app exposes the five endpoints from the spec plus serves `web/` statically. Endpoints delegate to `queries.py`. The output dir is read from `config.OUT_DIR` so tests can point it at a seeded tmp dir.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.app'`.

- [ ] **Step 3: Implement `api/app.py`**

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from recovery import config, queries

app = FastAPI(title="eu-ukr-recovery-money")
WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@app.get("/api/kpi")
def get_kpi(sector: str | None = None, region: str | None = None):
    return queries.kpi(config.OUT_DIR, sector=sector, region=region)


@app.get("/api/sankey")
def get_sankey(sector: str | None = None, region: str | None = None):
    return queries.sankey(config.OUT_DIR, sector=sector, region=region)


@app.get("/api/supplier/{edrpou}")
def get_supplier(edrpou: str):
    return queries.supplier(config.OUT_DIR, edrpou)


@app.get("/api/gaps")
def get_gaps(type: str = "contract_no_payment"):
    return queries.gaps(config.OUT_DIR, gap_type=type)


@app.get("/api/funnel")
def get_funnel():
    return queries.funnel(config.OUT_DIR)


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_api.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add api/__init__.py api/app.py tests/test_api.py
git commit -m "feat: FastAPI app exposing query endpoints"
```

---

### Task 10: Web frontend (d3-sankey + KPI + filters)

**Files:**
- Create: `web/index.html`
- Test: manual (documented below)

No JS unit framework — keep it a single static file using d3 from CDN. It fetches `/api/kpi` and `/api/sankey` with the current filters, renders the KPI band and the Sankey, and a GAPS table from `/api/gaps`.

- [ ] **Step 1: Write `web/index.html`**

```html
<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <title>Гроші на відбудову України</title>
  <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
  <script src="https://cdn.jsdelivr.net/npm/d3-sankey@0.12"></script>
  <style>
    body { font-family: system-ui, sans-serif; margin: 1.5rem; color: #1a1a1a; }
    .kpi { display: flex; gap: 1rem; margin-bottom: 1rem; }
    .kpi div { background: #f3f4f6; padding: .75rem 1rem; border-radius: .5rem; }
    .kpi b { display: block; font-size: 1.25rem; }
    select { padding: .35rem; }
    .break { color: #b91c1c; }
    table { border-collapse: collapse; margin-top: 1rem; width: 100%; }
    td, th { border: 1px solid #ddd; padding: .35rem .5rem; font-size: .9rem; }
  </style>
</head>
<body>
  <h1>Наскрізний слід грошей на відбудову України</h1>
  <p>ProZorro → казначейські виплати (ядро) + TED overlay. Дані: разовий знімок, останні 12 міс.</p>

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

  <div class="kpi" id="kpi"></div>
  <svg id="sankey" width="900" height="320"></svg>
  <h2>Обриви ланцюга (контракт без виплати)</h2>
  <table id="gaps"><thead><tr>
    <th>Контракт</th><th>Виконавець</th><th>CPV</th><th>Регіон</th><th>Сума, грн</th>
  </tr></thead><tbody></tbody></table>

  <script>
    const fmt = n => new Intl.NumberFormat("uk-UA").format(n);

    async function refresh() {
      const sector = document.getElementById("sector").value;
      const q = sector ? `?sector=${sector}` : "";

      const kpi = await (await fetch(`/api/kpi${q}`)).json();
      document.getElementById("kpi").innerHTML = `
        <div>Оголошено (TED), €<b>${fmt(kpi.announced_eur)}</b></div>
        <div>Законтрактовано, грн<b>${fmt(kpi.contracted_uah)}</b></div>
        <div>Виплачено, грн<b>${fmt(kpi.paid_uah)}</b></div>
        <div class="break">Обриви<b>${fmt(kpi.breaks)}</b></div>`;

      const data = await (await fetch(`/api/sankey${q}`)).json();
      drawSankey(data);

      const gaps = await (await fetch(`/api/gaps?type=contract_no_payment`)).json();
      const tbody = document.querySelector("#gaps tbody");
      tbody.innerHTML = gaps.map(g => `<tr>
        <td>${g.contract_id}</td><td>${g.supplier_name ?? ""}</td>
        <td>${g.cpv_div ?? ""}</td><td>${g.region ?? ""}</td>
        <td>${fmt(g.contract_amount_uah ?? 0)}</td></tr>`).join("");
    }

    function drawSankey(data) {
      const svg = d3.select("#sankey"); svg.selectAll("*").remove();
      const { nodes, links } = d3.sankey()
        .nodeWidth(18).nodePadding(20)
        .extent([[1, 1], [880, 300]])({
          nodes: data.nodes.map(d => ({ ...d })),
          links: data.links.map(d => ({ ...d })),
        });
      svg.append("g").selectAll("rect").data(nodes).join("rect")
        .attr("x", d => d.x0).attr("y", d => d.y0)
        .attr("height", d => Math.max(1, d.y1 - d.y0))
        .attr("width", d => d.x1 - d.x0).attr("fill", "#2563eb");
      svg.append("g").attr("fill", "none").selectAll("path").data(links).join("path")
        .attr("d", d3.sankeyLinkHorizontal())
        .attr("stroke", "#93c5fd")
        .attr("stroke-width", d => Math.max(1, d.width)).attr("opacity", .6);
      svg.append("g").selectAll("text").data(nodes).join("text")
        .attr("x", d => d.x0 < 440 ? d.x1 + 6 : d.x0 - 6)
        .attr("y", d => (d.y1 + d.y0) / 2).attr("dy", "0.35em")
        .attr("text-anchor", d => d.x0 < 440 ? "start" : "end")
        .text(d => d.name).style("font-size", "12px");
    }

    document.getElementById("sector").addEventListener("change", refresh);
    refresh();
  </script>
</body>
</html>
```

- [ ] **Step 2: Manual verification**

Run: `.venv/Scripts/python -m uvicorn api.app:app --reload` (after `python run.py --max-pages 2` has produced `data/out/chain.parquet`), open `http://127.0.0.1:8000/`.
Expected: KPI band shows numbers, the Sankey renders two flows (contracted → paid), the gaps table lists `contract_no_payment` rows, and changing the sector filter updates all three.

- [ ] **Step 3: Commit**

```bash
git add web/index.html
git commit -m "feat: thin web UI (d3-sankey, KPI band, sector filter, gaps table)"
```

---

### Task 11: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

Document: the one-line pitch and the `ProZorro → spending (core) + TED (overlay)` diagram; the honest note that TED is a confidence-tagged overlay (and why, per the spec); quickstart (`pip install -e ".[dev]"`, `python run.py`, `uvicorn api.app:app`); the stage table; the data-contract Parquet schemas; and a "Gaps & honesty" section explaining the funnel and the `state` tags. Link to `docs/superpowers/specs/2026-06-03-eu-ukr-recovery-money-design.md`.

- [ ] **Step 2: Run the full test suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README (pitch, quickstart, stages, data contract, honesty)"
```

---

## Self-Review

**Spec coverage:**
- Staged Parquet pipeline + DuckDB → Tasks 4–8. ✓
- ProZorro↔spending core join on EDRPOU → Task 5 `join_core`. ✓
- TED overlay with `match_confidence` → Task 5 `attach_ted_overlay`. ✓
- Chain state tags (`full`, `contract_no_payment`, `payment_no_ted`) → Task 6. ✓
- Feasibility funnel → Task 6 `build_funnel`, surfaced via Task 8 `funnel` + Task 9 `/api/funnel`. ✓
- Five FastAPI endpoints (sankey/kpi/supplier/gaps/funnel) → Task 9. ✓
- Thin web: Sankey + KPI band + sector filter + gaps table (Ukrainian) → Task 10. ✓
- CPV scope `45/71/09/31/34`, 12-month window → Task 0 config. ✓
- Live API + on-disk cache, manual one-time snapshot → Tasks 2, 3, 7. ✓
- Honest gaps (no silent drop), redaction tag → normalize keeps `redacted`; gaps surfaced via state tags and funnel. ✓
- Tests: normalizer units, join cases, pipeline smoke → Tasks 1, 5, 6, 7. ✓

**Out-of-scope items confirmed deferred (per spec):** geo-mapping, opendatabot, КПКВК donor tagging, scheduled refresh, bulk XML. Not in any task. ✓

**Note on API response shapes:** the exact JSON field names for spending.gov.ua (`recipt_edrpou`, `trans_date`, `payment_details`) and TED v3 (`publication-number`, `classification-cpv`, `winner-name`) are best-effort from the recon notes; the engineer must verify against a live response in Task 3 and adjust the fixture + normalizer field names together if they differ. The normalizers (Task 4) are isolated precisely so this adjustment touches one mapping function per source.

**Type consistency:** `cpv_div`, `supplier_edrpou`/`recipient_edrpou`, `supplier_name_norm`/`winner_name_norm`, `paid_amount_uah`, `contract_amount_uah`, `ted_amount_eur`, `ted_match_confidence`, `state` are used consistently across Tasks 4–10. ✓
