# UI Upgrade — Design

Make the `eu-ukr-recovery-money` web dashboard **more informative** and **more
responsive**. The current UI (`web/index.html`) shows a KPI band, a CPV sector
dropdown, a 3-node Sankey, and a gaps table. The API already exposes data the UI
does not surface (feasibility funnel, region filter, supplier detail). This upgrade
turns the page into a single-scroll responsive dashboard that uses all of it, plus a
few small new query/endpoint additions.

## Goals

1. **Informative:** show the feasibility funnel, a state breakdown, top suppliers and
   top regions, click-through supplier detail, and explanatory context (% paid, weak-TED
   note, tooltips, state explanations).
2. **Responsive:** adaptive layout (mobile → desktop), fast feedback (loading states,
   smooth transitions, no flicker), interactivity (combined sector+region filters,
   sortable gaps table, drill-down to a supplier card), and visual polish.

## Decisions

| Decision | Choice |
|----------|--------|
| Layout | Single scrollable page, sticky filter header |
| Sections (top→bottom) | Filters → KPI band → Funnel + state bars → wide Sankey → Top suppliers + Top regions → sortable gaps table |
| Supplier detail | Modal card opened by clicking a gaps-table row or a supplier name |
| Code structure | No build step. Split static assets: `web/index.html` + `web/app.js` + `web/styles.css`, served by the existing `StaticFiles` mount. Vanilla JS + d3 from CDN. |
| Filters | `sector` (CPV division) and `region` combine; apply to KPI, Sankey, breakdown, top, and gaps |
| State colors | `full` = green (#15803d), `payment_no_ted` = grey (#6b7280), `contract_no_payment` = red (#b91c1c) |

## Architecture

The frontend stays a no-build static bundle (`index.html` shell + `styles.css` + `app.js`)
served from `web/` via the FastAPI `StaticFiles` mount and the existing `GET /` route.
`app.js` fetches the JSON endpoints, renders each section, and re-renders on filter change.
The backend gains a few small read-only query functions in `recovery/queries.py` and thin
FastAPI endpoints that delegate to them — same pattern as the existing five endpoints.

```
web/index.html  (semantic shell: header, sections, modal container)
web/styles.css  (responsive grid, state colors, cards, skeletons)
web/app.js      (fetch + render + interactions; one render fn per section)
        │  fetch
        ▼
FastAPI /api/{kpi,sankey,gaps,funnel,supplier,regions,breakdown,top}
        │
   recovery.queries  (DuckDB over chain.parquet / funnel.parquet)
```

## Backend additions (recovery/queries.py + api/app.py)

New query functions and endpoints (all read `config.OUT_DIR`, follow the existing
`_conn` / `_where` helpers and `?`-bound filters):

- `regions(out_dir) -> list[str]` — distinct non-null `region` values from chain, sorted.
  Endpoint: `GET /api/regions`.
- `breakdown(out_dir, sector=None, region=None) -> list[dict]` — per-`state` rows
  `{state, count, contracted_uah, paid_uah}`. Endpoint: `GET /api/breakdown?sector=&region=`.
- `top(out_dir, by, sector=None, region=None, limit=10) -> list[dict]` — top entities by
  contracted amount. `by="supplier"` groups by `supplier_edrpou` returning
  `{edrpou, supplier_name, contracted_uah, paid_uah, contracts}`; `by="region"` groups by
  `region` returning `{region, contracted_uah, paid_uah, contracts}`. `by` is validated
  against an allowlist (`{"supplier","region"}`) — never interpolated raw into SQL.
  Endpoint: `GET /api/top?by=supplier|region&sector=&region=&limit=`.
- Extend `gaps(out_dir, gap_type="contract_no_payment", sector=None, region=None)` —
  add optional `sector`/`region` filters so the gaps table honors the global filters.
  The `/api/gaps` endpoint gains `sector` and `region` query params.

`kpi` and `sankey` already accept `sector`/`region`; `supplier` already returns a
supplier's contracts. No change needed to those query signatures. The Sankey keeps its
current shape (contracted→paid sized in UAH; `announced_eur` returned separately, shown
as context, since EUR and UAH cannot share one flow scale).

## Frontend behavior (web/app.js)

- On load and on any filter change: read `sector` + `region`, build the shared query
  string, and refresh all sections. Filter changes are debounced (~150 ms) and the
  affected sections show a lightweight skeleton/spinner until their fetch resolves.
- One render function per section (`renderKpi`, `renderFunnel`, `renderStateBars`,
  `renderSankey`, `renderTop`, `renderGaps`, `renderSupplierModal`), each taking the
  fetched data and updating its own DOM subtree in place (no full-page wipe → no flicker).
- `renderSankey` reads its container width and redraws on resize (ResizeObserver), so the
  chart is fluid rather than a fixed 900px.
- Gaps table: client-side sortable by column (contract sum, supplier, cpv, region). A row
  click opens the supplier modal (fetch `/api/supplier/{edrpou}`).
- All interpolated API strings are HTML-escaped (keep the existing `esc()` helper).
- Every section has explicit empty and error states (e.g. "Дані ще не згенеровано —
  запустіть пайплайн").

## Context & honesty surfacing

- KPI band shows **% paid of contracted** alongside the absolute paid figure.
- The funnel and state bars make the "where the chain breaks" story visible at a glance.
- TED-overlay items display a visible **"слабкий TED-збіг"** note (driven by
  `ted_match_confidence`), keeping the design's honesty about the weak left side.
- Short inline explanations / tooltips define each state and the Sankey stages.

## Testing

- **Backend (TDD):** unit tests for `regions`, `breakdown`, `top` (incl. `by` allowlist
  rejection of bad input), and the extended `gaps` sector/region filters; API tests for
  the new/extended endpoints via `TestClient`, seeding a small chain/funnel parquet.
- **Frontend (static, no framework):** the existing approach — seed a synthetic dataset,
  start the server, assert `GET /` serves the shell and `web/app.js` + `web/styles.css`
  are served, and that the new endpoints return data. Visual rendering is verified in a
  browser (cannot be asserted headlessly).

## README

Update `README.md` (English): add a "Dashboard" section describing the single-page layout,
combined filters, funnel, state breakdown, top suppliers/regions, sortable gaps table and
supplier modal; refresh the API-endpoints table with `regions`, `breakdown`, `top` and the
extended `gaps`; keep the honesty section. Clear and detailed.

## Out of scope (YAGNI)

- Geo map of objects, CSV export, beneficial-ownership enrichment, КПКВК donor tagging,
  `gaps_*.parquet` per-stage artifacts / orphan-spending surfacing (tracked separately).
- Any build step, bundler, or JS framework.
- Fixing the live-ingest API formats (TED 400) — separate follow-up; this upgrade runs on
  the same pipeline output (real or `scripts/seed_demo.py`).
