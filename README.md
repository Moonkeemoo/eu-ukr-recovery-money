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

# 2. Run the pipeline (fetches live APIs, caches responses on disk)
python run.py

# Limit pages during development (faster, smaller dataset):
python run.py --max-pages 5

# 3. Serve the UI
uvicorn api.app:app --reload

# Open http://127.0.0.1:8000/
```

Data is a **one-time snapshot** — re-running `run.py` replays from the on-disk cache (`data/cache/`) unless you delete it. The live APIs are unauthenticated public endpoints.

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
- `src/recovery/queries.py` — DuckDB query layer: `kpi`, `sankey`, `supplier`, `gaps`, `funnel`.
- `api/app.py` — FastAPI app exposing the query layer at `/api/*` and serving `web/index.html` at `/`.
- `web/index.html` — Ukrainian-language UI: KPI band, d3-sankey diagram, sector filter, gaps table.

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

## API endpoints

Once `uvicorn api.app:app` is running:

| Endpoint | Description |
|----------|-------------|
| `GET /api/kpi?sector=45&region=...` | Aggregate totals: contracted UAH, paid UAH, announced EUR, break count |
| `GET /api/sankey?sector=45` | Sankey node/link data for the d3 diagram |
| `GET /api/supplier/{edrpou}` | Per-supplier contract list |
| `GET /api/gaps?type=contract_no_payment` | Contracts matching the given gap state |
| `GET /api/funnel` | Feasibility funnel step counts |
| `GET /` | Ukrainian UI (served from `web/index.html`) |

---

## Project structure

```
.
├── run.py                        # Pipeline entry point
├── api/
│   └── app.py                    # FastAPI application
├── web/
│   └── index.html                # Ukrainian Sankey UI
├── src/recovery/
│   ├── config.py                 # Constants and API hosts
│   ├── clients.py                # CachedClient (httpx + disk cache)
│   ├── normalize_fields.py       # EDRPOU, name, CPV normalizers
│   ├── stage1_ingest.py          # API fetch layer
│   ├── stage2_normalize.py       # Raw → typed Polars DataFrames
│   ├── stage3_join.py            # Core join + TED overlay
│   ├── stage4_chain.py           # State tagging + funnel
│   └── queries.py                # DuckDB query layer
├── tests/                        # pytest suite (31 tests)
├── data/
│   ├── cache/                    # On-disk API response cache
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
