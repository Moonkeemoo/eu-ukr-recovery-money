# Real-Data Ingest (ProZorro + spending) — Design

Make `python run.py` actually pull **real** data from the live ProZorro and
spending.gov.ua APIs so the dashboard shows genuine Ukrainian reconstruction contracts
and payments, instead of the synthetic `scripts/seed_demo.py` dataset. TED stays
deferred (its v3 search returns 400 with our current query and is out of scope here).

## Why this is needed

The current `stage1_ingest.pull_prozorro` / `pull_spending` were written against
best-effort field names that do not match the live APIs, so `run.py` fails. Live probing
(2026-06-03) established the real contracts:

**ProZorro** (`https://public-api.prozorro.gov.ua/api/2.5`)
- `GET /contracts?descending=1` → a change-feed stub: `{"data": [{"id", "dateModified"}], "next_page": {"offset", "path"}}`, newest-first. There is **no server-side CPV filter**.
- `GET /contracts/{id}` → the full record: `data.contractID`, `data.items[].classification.id` (CPV; `scheme="ДК021"`), `data.suppliers[].identifier.id` (EDRPOU; `scheme="UA-EDR"`), `data.suppliers[].name`, `data.suppliers[].address.region`, `data.value.amount`, `data.dateSigned`.
- Fair use ~700 req/min.

**spending.gov.ua** (`https://api.spending.gov.ua/api/v2/api/transactions/` — trailing slash required)
- Query params: `recipt_edrpous` (**plural**, comma-separated list), `payers_edrpous`, `regions`, `startdate`/`enddate` (`YYYY-MM-DD`, **max 92-day range**), `sumFrom`/`sumTo`, `kpk`.
- Response is a **bare JSON list**; each row has `id, trans_date, amount, payer_edrpou, payer_name, recipt_edrpou, recipt_name, payment_details, region_id, kekv, kpk, contractId, contractNumber, budgetCode, …`.
- A single recipient can return thousands of rows per quarter (multi-MB payloads).

The good news: `normalize_spending` already reads the correct field names
(`recipt_edrpou/recipt_name/amount/trans_date/payment_details/id`), and
`normalize_prozorro` already reads the correct contract fields. The bugs are confined to
the two `pull_*` functions (wrong endpoint shape, wrong params, wrong pagination).

## Decisions

| Decision | Choice |
|----------|--------|
| Sources | ProZorro + spending live; TED deferred (best-effort, non-fatal) |
| Sample size | Medium: target ~500 in-scope contracts, scan cap ~1500 newest |
| Spending window | Last 12 months, split into 4 quarterly windows (each ≤ 92 days) |
| Spending batching | Dedupe supplier EDRPOUs; batch ~20 per `recipt_edrpous` request |
| Strategy | Live API walk + on-disk cache (rejected: bulk XML/dump downloads — overkill for 500) |
| Join | Unchanged: ProZorro winner EDRPOU = spending recipient EDRPOU (`contractId`-level join deferred — YAGNI) |
| Config | `PROZORRO_TARGET=500`, `PROZORRO_SCAN_CAP=1500`, `SPENDING_BATCH=20`, `SPENDING_WINDOW_DAYS=90`; `run.py` CLI overrides |

## Architecture

Only the ingest layer changes. Stages 2–4, the query layer, the API, and the web UI are
untouched — they consume the same normalized frames and Parquet artifacts as before. The
demo seeder (`scripts/seed_demo.py`) remains as a fallback for offline/instant demos.

```
ProZorro /contracts?descending=1 ──► [walk feed, fetch each /contracts/{id}, keep in-scope CPV]
                                              │ (full contract records)
                                              ▼
spending /v2/api/transactions/  ◄── [dedupe supplier EDRPOUs → batched, quarterly windows]
                                              │
                          stage2 normalize → stage3 join → stage4 chain (UNCHANGED)
                                              │
                                       data/out/*.parquet → DuckDB → FastAPI → dashboard
```

## Component changes

### `src/recovery/config.py`
Add: `PROZORRO_TARGET = 500`, `PROZORRO_SCAN_CAP = 1500`, `SPENDING_BATCH = 20`,
`SPENDING_WINDOW_DAYS = 90`. Keep `WINDOW_MONTHS = 12`.

### `src/recovery/stage1_ingest.py` — `pull_prozorro` (rewrite)
- Walk `GET {PROZORRO_OCDS}/contracts?descending=1`, following `next_page.offset` (param
  `offset`) page to page.
- For each feed stub id, `GET {PROZORRO_OCDS}/contracts/{id}` (cached); read `data`.
- Keep the contract if any `data.items[].classification.id` is `config.cpv_in_scope(...)`.
- Stop when `target` in-scope contracts collected OR `scan_cap` stubs scanned.
- Signature: `pull_prozorro(cache_dir, target=config.PROZORRO_TARGET, scan_cap=config.PROZORRO_SCAN_CAP) -> list[dict]` returning full contract `data` dicts.

### `src/recovery/stage1_ingest.py` — `pull_spending` (rewrite)
- Endpoint `{SPENDING_API}/v2/api/transactions/` (trailing slash).
- Input: list of recipient EDRPOUs. Dedupe, batch `SPENDING_BATCH` per request as a
  comma-joined `recipt_edrpous`.
- For each batch, iterate quarterly windows covering the last `WINDOW_MONTHS` (each window
  ≤ `SPENDING_WINDOW_DAYS` days), passing `startdate`/`enddate` (`YYYY-MM-DD`).
- Response is a bare list; extend the output. Cache per (batch, window).
- Signature: `pull_spending(cache_dir, edrpous, batch=config.SPENDING_BATCH, window_days=config.SPENDING_WINDOW_DAYS, months=config.WINDOW_MONTHS, today=None) -> list[dict]`. `today` is injectable for deterministic tests (default: real current date).

### `src/recovery/stage2_normalize.py` — `normalize_prozorro` (small change)
Region fallback: `items[0].deliveryAddress.region` → else `suppliers[0].address.region`.
`normalize_spending` unchanged.

### `run.py` — TED non-fatal
Wrap the TED pull+normalize in try/except: on any error, log a warning and use an empty TED
frame (via `normalize_ted([])`, which already yields a correctly-typed empty frame). The
pipeline then completes on ProZorro + spending; the TED overlay is simply empty. ProZorro
and spending pulls use the new signatures; `run.py` gains `--target` / `--scan-cap` CLI args.

## Date handling

`Date.now()`-style calls are fine in `run.py` (real run), but the spending window math must
be unit-testable. `pull_spending` accepts an injectable `today` (defaults to the real
current date inside the function, not at import) so tests pass a fixed date and assert the
exact window boundaries.

## Error handling

- Per-contract fetch failure (404/5xx/network): log and skip that contract, continue the walk.
- Spending request failure for a batch/window: retry via the existing `CachedClient`
  backoff; on persistent failure, log and skip that batch/window (partial data over crash).
- TED failure: non-fatal (see above).
- Honest logging: print how many contracts scanned vs kept, how many EDRPOUs queried, and
  any skipped batches — no silent truncation.

## Testing

- **`pull_prozorro`** (respx): mock the descending feed (two pages via `next_page`) and the
  per-id contract fetches; assert it follows pagination, fetches each id, keeps only
  in-scope-CPV contracts, and stops at `target`/`scan_cap`. Fixtures use the **real** shapes
  (feed stub `{data:[{id,dateModified}], next_page:{offset}}`; full contract with
  `items[].classification.id` scheme `ДК021`, `suppliers[].identifier.id` scheme `UA-EDR`).
- **`pull_spending`** (respx): mock `/v2/api/transactions/` returning a bare list; inject a
  fixed `today`; assert EDRPOU batching (comma-joined `recipt_edrpous`), quarterly window
  boundaries (≤92 days), and list concatenation.
- **`normalize_prozorro`**: region fallback to supplier address when delivery region absent.
- **`run.py` smoke**: monkeypatch the three pulls (TED raising) and assert the pipeline
  still writes `chain.parquet` (TED-non-fatal path) — extends the existing smoke test.
- Existing stage2/3/4/queries/api tests remain green (no contract changes there).

## Out of scope (YAGNI)

- TED live-ingest fix (separate follow-up).
- `contractId`/`contractNumber`-level precise join, `kpk`/donor-program tagging, `region_id`
  enrichment (note the data is now available; defer the features).
- Concurrency/async fetching (sequential + cache is adequate at this scale; revisit only if
  the ~5–10 min first run is too slow).
- Bulk dump ingestion.
