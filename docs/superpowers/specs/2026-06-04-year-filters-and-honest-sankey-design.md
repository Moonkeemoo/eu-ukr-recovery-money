# Year filters + honest Sankey — design

**Date:** 2026-06-04
**Branch:** `feature/real-data-ingest`
**Status:** design, pending implementation

## Motivation

Live-running the pipeline (after the TED and spending-batch ingest fixes) surfaced three
issues while exploring the dashboard:

1. **No way to slice by year.** The dashboard only filters by CPV sector and region.
2. **Sankey reads as "contracted = paid".** Flows carry no numeric labels, and the
   "Оголошено (TED)" → "Законтрактовано" link is value-scaled in UAH even though the TED
   amount is in EUR — so the TED node visually equals the contracted node.
3. **`paid` is 62× `contracted`** on real data. Treasury transactions carry no
   `contractId` (the field is null), so a payment can only be attributed to a supplier by
   EDRPOU. `paid` is therefore the supplier's **total** treasury inflow over the window,
   not money paid for these specific contracts. This is a data limit, not a bug.

## Decisions (agreed with user)

| Topic | Decision |
|-------|----------|
| Year filter axes | **Both, separate**: a contract-year filter and a payment-year filter |
| Payment-year data model | **Year-accurate** (approach B): a side table of payments aggregated by year |
| Sankey fix | **Labels + decouple TED**: numeric labels on nodes/flows; TED link no longer UAH-scaled |
| Paid attribution | **Relabel honestly**: `paid` is supplier-level treasury inflow, named and noted as such — numbers kept as-is |

## Data model

### `contract_year` (new column on contracts/chain)
`normalize_prozorro` currently drops `data.dateSigned`. Add a nullable `contract_year`
(`Int64`) parsed as `int(dateSigned[:4])`; contracts without a signing date get `null`
(surfaced in the UI as "невідомо"). Carries through join into `chain.parquet`.

### `paid_by_year.parquet` (new side table)
`join_core` keeps the total `paid_amount_uah` per contract as today, and **additionally**
writes `data/out/paid_by_year.parquet` with rows `(contract_id, year, paid_uah)` — payments
aggregated per contract per calendar year of `payment_date`. A relational side table is
preferred over a nested map column because `queries.py` already joins parquet relations in
DuckDB, and a `MAP`/struct column is awkward to query and round-trips poorly through
polars→parquet→DuckDB.

## Query layer (`queries.py`)

A single helper builds the filtered relation that every query function reads from:

```
_relation(con, sector, region, contract_year, payment_year) -> view name "q"
```

- **sector / region**: unchanged row-level predicates.
- **contract_year**: row-level `WHERE contract_year = ?`.
- **payment_year**: `LEFT JOIN paid_by_year py ON py.contract_id = chain.contract_id AND py.year = ?`.
  When a payment-year is set, the effective `paid_amount_uah` becomes `py.paid_uah` (that
  year's sum) and rows are restricted to those with a payment that year. `contract_amount_uah`
  stays the full contract value (a contract is not split across years) — documented as a
  known semantic: under a payment-year filter, "contracted" is the full value of contracts
  that saw a payment that year.
- **state** stays computed on lifetime totals (in `stage4_chain`); filters only restrict which
  rows show and which `paid` value is summed. Under a payment-year filter, `contract_no_payment`
  rows naturally drop out (they have no payments in any year).

All of `kpi`, `sankey`, `breakdown`, `top`, `gaps` read from `q`. `funnel` and `regions`
are unaffected by year (regions list stays global; funnel stays lifetime).

### New endpoint
`GET /api/years` → `{"contract_years": [...], "payment_years": [...]}` (descending, nulls
excluded). Backs the two UI selects.

All filtered endpoints gain optional `contract_year` and `payment_year` query params.

## UI (`web/app.js`, `web/index.html`)

### Year filters
Two selects beside the existing Sector/Region controls: **"Рік контракту"** and
**"Рік виплати"**, each defaulting to "усі". Populated from `/api/years`. Selecting a value
sets `state.contract_year` / `state.payment_year` and re-runs the existing `onFilter()` flow
(appended to the query string of every data call).

### Honest paid label
`paid` is supplier-level, so:
- KPI card "Виплачено, грн" → **"Надходження постачальникам, грн"** with a sub-note:
  "усі казначейські виплати компаніям-виконавцям, не лише за ці контракти".
- Sankey node "Виплачено" → **"Надходження постачальникам"**.
- A short disclaimer line under the Sankey states the supplier-level attribution and that
  treasury data carries no contract link.

### Sankey clarity

**Open problem the honest data exposes:** a Sankey is a *conserved-flow* diagram — a node
cannot emit more than it receives. With supplier-level attribution, `paid` (≈85.7 млрд) is
far larger than `contracted` (≈1.37 млрд), so a contracted→paid flow forces the
"Законтрактовано" node to balloon to the paid magnitude. Numeric labels do not fix this; the
flow metaphor itself misrepresents two non-conserved, differently-scoped quantities.

**Proposed resolution (confirm during review):** stop forcing the two UAH quantities into one
conserved flow. Render the dashboard's money picture as **labelled magnitude bars**, not a
Sankey chain:

- A horizontal bar per quantity — Законтрактовано (грн), Надходження постачальникам (грн),
  Оголошено (TED, €) — each with its numeric label, on its own honest scale (EUR bar
  visually separated / annotated, never mixed into the UAH bars).
- This keeps the at-a-glance comparison the Sankey was meant to give, without implying a
  false left-to-right conservation. The "розрив" story (contracts with no payment) stays in
  the existing breakdown/funnel panels.

**Alternative (smaller change):** keep the three-node Sankey but (a) add numeric labels,
(b) render the TED→contracted link as a neutral dashed context connector (fixed thin width,
not UAH-scaled) with the "€…" announced label on the TED node, and (c) accept that the
contracted node sizes to the paid magnitude, leaning on labels + the disclaimer to carry the
honesty. Less work, but the geometry stays misleading.

Recommendation: the **bars** option — it is the only one that is visually honest once `paid`
is supplier-level. Decision deferred to user review.

## Out of scope (follow-ups)

- The 4 spending requests still returning HTTP 400 at `batch=10` (one batch contained an
  11-digit malformed EDRPOU). Now surfaced by the warning log; root-cause separately.
- Heuristic payment attribution (post-`dateSigned` only, budget-code `kpk`/`kekv` filtering).
  Explicitly declined in favour of honest relabeling for now.
- TED→ProZorro overlay match rate (0 matches on the current 362-contract sample) — a
  data-coverage issue, not addressed here.

## Testing

- `normalize_prozorro`: `contract_year` parsed from `dateSigned`; null when absent.
- `join_core` / new builder: `paid_by_year` rows aggregate correctly per contract per year;
  total `paid_amount_uah` unchanged.
- `queries`: contract-year filter restricts rows; payment-year filter yields that year's
  paid sum and drops no-payment rows; `_relation` composes with sector/region.
- `/api/years` returns sorted distinct years; filtered endpoints honour both params.
- Sankey query returns labelled values + announced EUR independent of the UAH flow.
