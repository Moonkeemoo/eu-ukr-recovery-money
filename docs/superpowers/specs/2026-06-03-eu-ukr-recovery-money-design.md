# eu-ukr-recovery-money — Design

**Tracing reconstruction money for Ukraine: from EU tenders (TED) through Ukrainian
procurement (ProZorro) to actual treasury payments (spending.gov.ua).** The product shows
who receives the money and where the chain "funding → contract → payment" breaks.

```
EU tender (TED)  ──▶  Ukrainian contract (ProZorro)  ──▶  treasury payment (spending.gov.ua)
   [overlay, weak]          [CORE, strong]                      [CORE, strong]
   name + CPV match         winner EDRPOU = recipient EDRPOU
```

> ### Status: full product with Sankey UI (not a feasibility spike)
> Unlike the `sanctioned-securities-trading-radar` spike, this repository builds the full
> product: a Sankey financial-trail dashboard with KPI band, supplier cards, a gaps view,
> and CSV export. It keeps the recon discipline (re-runnable staged pipeline, honest GAPS
> reporting, a feasibility funnel) **inside** a real UI.

## Core design decisions

| Decision | Choice |
|----------|--------|
| Format | Full product with Sankey UI |
| Chain framing | **ProZorro → spending is the core**; TED is an optional **overlay** shown where the supplier genuinely matches |
| Stack | Python pipeline + thin web (FastAPI + vanilla JS + `d3-sankey`) |
| Storage / serving | Staged **Parquet** artifacts + **DuckDB** query layer over Parquet (no separate ETL into a DB) |
| CPV scope | Extended reconstruction set: `45*` construction, `71*` engineering/design, `09*`/`31*` energy, `34*` transport |
| Time range | Last 12 months (≈ June 2025 → present) |
| Data acquisition | Live API + on-disk cache, one-time snapshot (manual re-run) |
| UI language | Ukrainian |

### Why TED is an overlay, not a mandatory left end

The recon critic's central point (verdict: *maybe*): most reconstruction money reaches Ukraine
as **budget support** (e.g. the Ukraine Facility), not as direct EU tenders won by Ukrainian
companies. TED only carries contracts where an EU body (ECHO, DG NEAR, EIB) is the direct
buyer — a small fraction. A `TED → ProZorro → spending` Sankey would therefore have an almost
empty left side for most cases. Additionally, TED's `company_reg_number` (BT-501) is the
buyer's **national** org ID, not necessarily a Ukrainian EDRPOU. So we treat the strong,
verifiable `ProZorro ↔ spending` join (shared EDRPOU) as the core, and surface TED only as a
confidence-tagged overlay where a supplier actually appears in both worlds.

## Architecture

A linear pipeline of Python stages. Each stage reads its input, writes a **Parquet** artifact,
is independently re-runnable, and logs every row it could **not** resolve (honest gaps over
fake success). The query layer is **DuckDB over the Parquet artifacts**. Serving is **FastAPI**
returning Sankey / KPI / detail JSON. The frontend is a lightweight static page (vanilla JS +
`d3-sankey`), no heavy SPA build.

```
TED API ─┐
ProZorro ─┼─► [1 ingest+cache] ─► [2 normalize] ─► [3 join] ─► [4 chain] ─► Parquet
spending ─┘                                                                   │
                                                              DuckDB ◄─────────┘
                                                                 │
                                                          FastAPI (JSON)
                                                                 │
                                                       web (d3-sankey + KPI)
```

## Pipeline stages

| Stage | Module | What it does |
|-------|--------|--------------|
| 1. Ingest | `stage1_ingest.py` | Pulls the 3 APIs filtered by CPV (`45/71/09/31/34`) and the 12-month window; caches raw responses under `data/cache/` for reproducibility; paginates respecting each API's rate limit. |
| 2. Normalize | `stage2_normalize.py` | Parses ProZorro OCDS, spending JSON, and TED notices into normalized tables: `prozorro_contracts`, `spending_tx`, `ted_notices`. Keys: EDRPOU (UA-EDR), CPV, company name, region. |
| 3. Join | `stage3_join.py` | **Core:** ProZorro winner EDRPOU = spending recipient EDRPOU (strong join). **Overlay:** TED winner ↔ ProZorro/spending via normalized company name + CPV category (weak; carries `match_confidence`). |
| 4. Chain | `stage4_chain.py` | Builds chain records `(TED?) → contract → payment`, tagging state: `full`, `contract_no_payment` (right-side break), `payment_no_ted` (no left end). Computes the feasibility funnel. |

`run.py` orchestrates all stages. Each stage is idempotent.

## Data model (key join fields)

- **EDRPOU** — the primary bridge ProZorro ↔ spending. Normalized to the canonical code form.
- **CPV category** — division level (first 2 digits) for sector filters and the weak TED bridge.
- **Normalized company name** — for the TED overlay where no shared ID exists. Transliterate /
  lowercase / strip legal forms (ТОВ / LLC / ПП …).
- **Region** — NUTS (TED) / ProZorro region — for the region filter.

## Serving (FastAPI endpoints)

- `GET /api/sankey?sector=&region=` — nodes and flows for the Sankey (announced → contracted → paid).
- `GET /api/kpi?sector=&region=` — announced / contracted / paid totals + break counts.
- `GET /api/supplier/{edrpou}` — a supplier's contracts (EU + UA) and payments.
- `GET /api/gaps?type=` — list of breaks (contract without payment, etc.), CSV export.
- `GET /api/funnel` — the feasibility funnel (how many records survived each join stage).

## Interface (thin web, Ukrainian)

Main screen — the **Sankey** of the reconstruction financial trail, with **CPV sector** and
**region** filters. A **KPI band** on top (announced / contracted / paid + break count).
Clicking a supplier node opens a **supplier card**. A separate **GAPS** tab — a table of breaks
with CSV export. A **Feasibility funnel** block honestly shows how many records actually linked
(especially the weak TED overlay).

## Error handling & honest gaps

- Each stage logs unresolved rows to `data/out/gaps_*.parquet` (no silent dropping).
- The TED overlay always carries `match_confidence` plus a visible "weak name/CPV match" note.
- ProZorro wartime redaction: redacted tenders are tagged `redacted`, not silently dropped.
- Rate-limit / network failures: retries with backoff; the cache lets a run resume.

## Testing

- Unit tests for the normalizers (EDRPOU, names, CPV) against fixed fixtures of raw API responses.
- Join-logic tests on synthetic cases: exact EDRPOU match, weak name match, break.
- A pipeline smoke test on a small cached slice (CI without network).

## Repo layout

```
eu-ukr-recovery-money/
├── README.md
├── pyproject.toml
├── run.py
├── src/recovery/        # stage1..4, normalize, join, chain
├── api/                 # FastAPI app
├── web/                 # index.html + d3-sankey
├── data/cache/  data/out/   # gitignored
├── tests/
└── docs/superpowers/specs/
```

## Out of scope (YAGNI for v1)

- Geo-mapping of reconstruction objects (deferred; the recon idea lists it as optional deepening).
- Beneficial-ownership enrichment (opendatabot).
- Donor-program tagging via budget program codes (КПКВК) — deferred; the TED overlay covers the
  EU-side signal for v1.
- Scheduled/automatic refresh (manual re-run only for v1).
- Bulk XML ingestion (the filtered 12-month slice is small enough for live API + cache).
