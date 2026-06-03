# eu-ukr-recovery-money

**Follow the full money trail from EU procurement announcements through Ukrainian contracts to treasury payments — in a single Sankey diagram.**

```
TED (EU notices) ──overlay──┐
                             ▼
ProZorro (contracts) ──── spending.gov.ua (payments)
         └── core join on EDRPOU ──────────────────┘
```

---

## Why TED is a confidence-tagged overlay, not the left anchor

Most reconstruction money reaches Ukraine as **budget support** (transfers to the state budget), not as direct EU tenders won by Ukrainian firms. That means:

- TED's `winner-country` rarely resolves to a Ukrainian supplier.
- TED's `company_reg_number` is the **buyer's** national organisation ID (typically an EU institution's identifier), not a Ukrainian EDRPOU.
- A TED → ProZorro → spending Sankey built on a direct ID join would have a near-empty left side for most realistic queries.

The **strong, verifiable join** is **ProZorro ↔ spending on shared EDRPOU** (Ukrainian company registration number). TED is surfaced only where a supplier's normalised name and CPV division match genuinely appear in both datasets, and the match is tagged with a confidence score (`1.0` when matched, `null` otherwise). The Sankey's left node ("Оголошено (TED)") shows aggregated EUR amounts for context; the structural flow is ProZorro → payments.

---

## Quickstart

```bash
# 1. Create a virtual environment and install
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"

# 2a. Run the full pipeline (live API pull, ~5–10 min first time)
python run.py

# Pull a smaller/faster sample during development:
python run.py --target 200 --scan-cap 800

# 2b. OR — seed synthetic demo data (instant, no network required)
#     Populates data/out/ with a small realistic dataset so the dashboard
#     can be explored without any live API pull.
python scripts/seed_demo.py

# 3. Serve the dashboard
uvicorn api.app:app --reload

# Open http://127.0.0.1:8000/
```

### What `python run.py` actually does

`run.py` performs a **real live-API pull** across two sources:

**ProZorro** — walks the `/contracts?descending=1` change-feed newest-first, fetches each full contract record, and keeps those whose CPV code belongs to a reconstruction division (45 / 71 / 09 / 31 / 34). The walk is bounded by two CLI flags:

| Flag | Default | Meaning |
|------|---------|---------|
| `--target` | 500 | stop after this many in-scope contracts are collected |
| `--scan-cap` | 1500 | hard cap on the total number of feed stubs scanned |

**spending.gov.ua** — calls the real `/v2/api/transactions/` endpoint. Recipient EDRPOUs extracted from the kept contracts are batched 20 per request (`SPENDING_BATCH = 20`) and queried over the last 12 months, split into ≤90-day windows (`SPENDING_WINDOW_DAYS = 90`) to stay within the API's 92-day hard limit.

All HTTP responses are cached under `data/cache/` (SHA-256-keyed, per `CachedClient`). **Re-runs are fast** — the network is only hit for cache misses.

### TED is deferred and non-fatal

The TED v3 search endpoint currently returns HTTP 400 for our CPV query format. `run.py` catches the error, logs `TED ingest skipped (non-fatal): ...`, and completes normally on ProZorro + spending data. The Sankey's "Оголошено (TED)" left node will simply be empty until the TED request format is resolved.

### Bounded sample — not the full corpus

`run.py` ingests the **newest ~500 reconstruction contracts** from ProZorro (the default `--target`). This is a bounded recent-data sample, not a full historical crawl. Use `--target` and `--scan-cap` to widen or narrow the sample.

---

## Pipeline stages

| Stage | Module | Job |
|-------|--------|-----|
| 1 — Ingest | `src/recovery/stage1_ingest.py` | Fetch ProZorro OCDS contracts, spending transactions (per EDRPOU), and TED notices; page through each source; persist raw JSON to `data/cache/` |
| 2 — Normalize | `src/recovery/stage2_normalize.py` | Parse each source into typed Polars DataFrames; normalise EDRPOU (8-digit zero-padded), company names (strip legal forms, lowercase), CPV divisions |
| 3 — Join | `src/recovery/stage3_join.py` | Left-join contracts to aggregated payments on EDRPOU (`join_core`); attach TED notices as overlay on `(supplier_name_norm, cpv_div)` (`attach_ted_overlay`) |
| 4 — Chain | `src/recovery/stage4_chain.py` | Tag each row with a `state` and write `chain.parquet`; compute the `funnel.parquet` count table |

Supporting modules:

- `src/recovery/config.py` — API base URLs, CPV scope, 12-month window constant, output paths.
- `src/recovery/clients.py` — `CachedClient`: httpx wrapper with SHA-256-keyed on-disk cache and exponential-backoff retry (3 attempts).
- `src/recovery/normalize_fields.py` — `normalize_edrpou`, `normalize_company_name`, `cpv_division`.
- `src/recovery/queries.py` — DuckDB query layer: `kpi`, `sankey`, `supplier`, `gaps`, `funnel`, `regions`, `breakdown`, `top`.
- `api/app.py` — FastAPI app exposing the query layer at `/api/*`, serving `web/index.html` at `GET /`, and mounting `web/` as `/static/*`.
- `web/index.html` — Dashboard HTML shell (Ukrainian language).
- `web/styles.css` — Responsive styles: sticky header, KPI band, bar charts, table, modal.
- `web/app.js` — Vanilla JS dashboard logic: filter wiring, section renderers, d3-sankey, supplier modal.
- `scripts/seed_demo.py` — Writes synthetic demo `chain.parquet` and `funnel.parquet` to `data/out/` for UI exploration without a live API pull.

---

## Data contract — Parquet schemas

### `prozorro_contracts.parquet`

| Column | Type | Notes |
|--------|------|-------|
| `contract_id` | Utf8 | `contractID` or `id` from OCDS |
| `cpv` | Utf8 | Full CPV code from first item classification |
| `cpv_div` | Utf8 | First 2 digits |
| `supplier_edrpou` | Utf8 | Normalised 8-digit EDRPOU |
| `supplier_name` | Utf8 | Raw name from API |
| `supplier_name_norm` | Utf8 | Lowercased, legal-form-stripped |
| `amount_uah` | Float64 | Contract value, UAH |
| `region` | Utf8 | Delivery address region |
| `redacted` | Boolean | True if contract details are redacted |

### `spending_tx.parquet`

| Column | Type | Notes |
|--------|------|-------|
| `tx_id` | Utf8 | Transaction `id` |
| `recipient_edrpou` | Utf8 | Normalised EDRPOU (`recipt_edrpou` upstream) |
| `recipient_name` | Utf8 | Raw name (`recipt_name` upstream) |
| `recipient_name_norm` | Utf8 | Normalised name |
| `amount_uah` | Float64 | Payment amount, UAH |
| `payment_date` | Utf8 | `trans_date` field from API |
| `purpose` | Utf8 | `payment_details` field |

### `ted_notices.parquet`

| Column | Type | Notes |
|--------|------|-------|
| `ted_id` | Utf8 | `publication-number` |
| `cpv` | Utf8 | `classification-cpv` |
| `cpv_div` | Utf8 | First 2 digits |
| `winner_name` | Utf8 | `winner-name` |
| `winner_name_norm` | Utf8 | Normalised winner name |
| `winner_country` | Utf8 | `winner-country` |
| `amount_eur` | Float64 | Contract value, EUR |
| `region` | Utf8 | `place-of-performance` |

### `chain.parquet`

One row per ProZorro contract, after join and state tagging.

| Column | Type | Notes |
|--------|------|-------|
| `contract_id` | Utf8 | |
| `supplier_edrpou` | Utf8 | |
| `supplier_name` | Utf8 | |
| `cpv_div` | Utf8 | |
| `region` | Utf8 | |
| `contract_amount_uah` | Float64 | |
| `paid_amount_uah` | Float64 | Sum of treasury payments for this EDRPOU; 0 if none found |
| `ted_amount_eur` | Float64 | From matched TED notice; null if no match |
| `ted_id` | Utf8 | TED publication number; null if no match |
| `ted_match_confidence` | Float64 | 1.0 if matched, null otherwise |
| `state` | Utf8 | See chain states below |

### `funnel.parquet`

| Column | Type | Notes |
|--------|------|-------|
| `step` | Utf8 | `contracts`, `with_payment`, `with_ted_overlay` |
| `count` | Int64 | Row count at that step |

---

## Gaps and honesty

### Feasibility funnel

`funnel.parquet` tracks the row count at each stage of confidence:

1. **contracts** — total ProZorro contracts in scope.
2. **with_payment** — contracts where at least one treasury payment was found for the supplier EDRPOU.
3. **with_ted_overlay** — contracts that additionally have a matched TED notice.

Most rows will sit at step 1 or 2; step 3 will be sparse for the reasons described above. This is expected and informative, not a bug.

### Chain state tags

Every row in `chain.parquet` carries one of three states:

| State | Meaning |
|-------|---------|
| `full` | Contract has both a treasury payment (`paid_amount_uah > 0`) and a TED match — the full chain is traceable |
| `contract_no_payment` | Contract exists in ProZorro but no payment found — right-side break; shown in the UI gaps table |
| `payment_no_ted` | Contract has a payment but no TED overlay — left end is missing; chain is ProZorro → spending only |

**`payment_no_contract` is intentionally absent.** Stage 3 is a contracts-left-join: spending rows with no matching ProZorro contract never reach `chain.parquet`. They are a gap, not a chain entry. This keeps the chain table clean and avoids conflating "unmatched spending" with "matched chain".

---

## Scope

| Dimension | Value |
|-----------|-------|
| CPV divisions | 45 (construction), 71 (engineering), 09 (energy raw materials), 31 (electrical equipment), 34 (transport) |
| Time window | 12 months rolling (`WINDOW_MONTHS = 12`) |
| UI language | Ukrainian |
| API auth | None — all three source APIs are public unauthenticated endpoints |

---

## A note on exact API field names

The field names used in `stage2_normalize.py` are **best-effort** based on documented API schemas at time of writing. In particular:

- **spending.gov.ua** uses the misspelling `recipt_edrpou` and `recipt_name` (not `receipt_*`) — this is the upstream API's spelling, deliberately preserved in the normalizer.
- **TED v3** uses hyphenated field names like `publication-number`, `classification-cpv`, `winner-name`, `winner-country`, `place-of-performance`.
- **ProZorro OCDS** nests supplier data under `suppliers[0].identifier.id` and CPV under `items[0].classification.id`.

If the live API changes field names, **`src/recovery/stage2_normalize.py` is the single place to update all per-source mappings.** No other module reads raw API responses.

---

## Dashboard

The UI at `http://127.0.0.1:8000/` is a single-scroll responsive dashboard. It is a **no-build static bundle** (`web/index.html` + `web/styles.css` + `web/app.js`) served directly by FastAPI at `GET /` and `/static/*`. No Node.js, no bundler. JavaScript and d3 are loaded from CDN (`d3@7` and `d3-sankey@0.12`).

### Layout (top to bottom)

1. **Sticky combined filters** — a CPV sector dropdown (all / 45 construction / 71 engineering / 09 energy / 31 electrical / 34 transport) and a region dropdown populated dynamically from `GET /api/regions`. All sections below re-render on change with a 150 ms debounce.

2. **KPI band** — four cards:
   - Announced (TED), € — sum of `ted_amount_eur` for matched notices.
   - Contracted, UAH — sum of `contract_amount_uah`.
   - Paid, UAH — sum of `paid_amount_uah` with a "% of contracted" sub-label.
   - Breaks (contract without payment) — count of `state = 'contract_no_payment'` rows.

3. **Two-column row:**
   - *Feasibility funnel* — horizontal bar chart of `GET /api/funnel` step counts (`contracts`, `with_payment`, `with_ted_overlay`). This panel is deliberately unfiltered (it shows whole-pipeline feasibility, not the current sector/region slice).
   - *State breakdown bars* — horizontal bars from `GET /api/breakdown` showing count and contracted UAH for each chain state (`full`, `payment_no_ted`, `contract_no_payment`), colour-coded by state class.

4. **Financial trail (Sankey)** — fluid `d3-sankey` diagram driven by `GET /api/sankey`. Nodes: "Оголошено (TED)" → "Законтрактовано" → "Виплачено". A note below the SVG explains whether TED data is present for the current slice. The diagram re-renders on container resize (ResizeObserver, 120 ms debounce).

5. **Two-column row:**
   - *Top suppliers* — table of top 10 suppliers by contracted UAH from `GET /api/top?by=supplier`. Each row is clickable and opens the supplier detail modal.
   - *Top regions* — table of top 10 regions by contracted UAH from `GET /api/top?by=region`.

6. **Gaps table** — sortable table of `state = 'contract_no_payment'` rows from `GET /api/gaps?type=contract_no_payment`. Columns: contract ID, supplier name, CPV division, region, contract amount UAH. Click any column header to sort ascending/descending. Each row is clickable and opens the supplier detail modal.

7. **Supplier detail modal** — slide-in overlay triggered by clicking a supplier row in the top-suppliers table or the gaps table. Calls `GET /api/supplier/{edrpou}` and renders a per-contract table (contract ID, CPV, region, contracted UAH, paid UAH, TED notice, state). Rows with a TED match display a **"слабкий TED-збіг"** ("weak TED match") tag as a reminder that the match is heuristic (name + CPV division). Close by clicking the × button or the backdrop.

---

## API endpoints

Once `uvicorn api.app:app` is running:

| Endpoint | Description |
|----------|-------------|
| `GET /api/kpi?sector=45&region=...` | Aggregate totals: contracted UAH, paid UAH, announced EUR, break count |
| `GET /api/sankey?sector=45&region=...` | Sankey node/link data for the d3 diagram |
| `GET /api/supplier/{edrpou}` | Per-supplier contract list |
| `GET /api/gaps?type=contract_no_payment&sector=&region=` | Contracts matching the given gap state; returns `contract_id`, `supplier_name`, `supplier_edrpou`, `cpv_div`, `region`, `contract_amount_uah`, `state` |
| `GET /api/funnel` | Feasibility funnel step counts (`contracts`, `with_payment`, `with_ted_overlay`) — not filtered by sector/region |
| `GET /api/regions` | Sorted list of distinct region strings present in `chain.parquet` |
| `GET /api/breakdown?sector=&region=` | Per-state row counts and contracted/paid UAH totals; used for the state breakdown bar chart |
| `GET /api/top?by=supplier\|region&sector=&region=&limit=10` | Top suppliers (by contracted UAH) or top regions; `limit` is 1–200, default 10 |
| `GET /` | Dashboard (served from `web/index.html`) |

---

## Project structure

```
.
├── run.py                        # Pipeline entry point
├── api/
│   └── app.py                    # FastAPI application
├── web/
│   ├── index.html                # Dashboard HTML shell (Ukrainian)
│   ├── styles.css                # Responsive dashboard styles
│   └── app.js                    # Vanilla JS dashboard logic + d3-sankey
├── scripts/
│   └── seed_demo.py              # Seed synthetic demo data (no live pull needed)
├── src/recovery/
│   ├── config.py                 # Constants and API hosts
│   ├── clients.py                # CachedClient (httpx + disk cache)
│   ├── normalize_fields.py       # EDRPOU, name, CPV normalizers
│   ├── stage1_ingest.py          # API fetch layer
│   ├── stage2_normalize.py       # Raw → typed Polars DataFrames
│   ├── stage3_join.py            # Core join + TED overlay
│   ├── stage4_chain.py           # State tagging + funnel
│   └── queries.py                # DuckDB query layer
├── tests/                        # pytest suite
├── data/
│   ├── cache/                    # On-disk API response cache (populated on first run)
│   └── out/                      # Parquet artifacts
└── docs/superpowers/
    ├── specs/2026-06-03-eu-ukr-recovery-money-design.md
    └── plans/2026-06-03-eu-ukr-recovery-money.md
```

---

## References

- Design document: [docs/superpowers/specs/2026-06-03-eu-ukr-recovery-money-design.md](docs/superpowers/specs/2026-06-03-eu-ukr-recovery-money-design.md)
- Implementation plan: [docs/superpowers/plans/2026-06-03-eu-ukr-recovery-money.md](docs/superpowers/plans/2026-06-03-eu-ukr-recovery-money.md)
- ProZorro public API: <https://public-api.prozorro.gov.ua/api/2.5>
- spending.gov.ua API: <https://api.spending.gov.ua/api>
- TED v3 search API: <https://api.ted.europa.eu/v3/notices/search>
