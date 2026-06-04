# eu-ukr-recovery-money

Money-trail pipeline: ProZorro contracts ↔ spending.gov.ua payments (core join on
EDRPOU), TED notices as an EDRPOU overlay → DuckDB query layer → FastAPI + vanilla-JS
dashboard. See @README.md for the full picture.

## Commands
- Tests: `.venv/Scripts/python.exe -m pytest -q`
- Live pipeline: `python run.py --target 500 --scan-cap 1500`
- Demo data (no network): `python scripts/seed_demo.py`
- Serve dashboard: `uvicorn api.app:app --reload` → http://127.0.0.1:8000/

## On Windows (this dev box)
- Use `.venv/Scripts/python.exe`, never bare `python`.
- Prefix any command that prints Cyrillic with `PYTHONIOENCODING=utf-8` — the cp1252
  console raises `UnicodeEncodeError` otherwise.
- Restart `uvicorn` after code changes (background runs have no `--reload`); a stale
  server serves old routes (e.g. 404 on a newly added endpoint).

## Structure
- `src/recovery/stage{1..4}_*.py` — ingest → normalize → join → chain
- `src/recovery/normalize_fields.py` — EDRPOU / name / CPV normalizers; **the single
  place to fix any per-source API field mapping**
- `src/recovery/queries.py` — DuckDB query layer (consumed by `api/app.py`)
- `web/` — no-build static dashboard (no d3-sankey; uses labelled magnitude bars)
- `data/out/` (Parquet) and `data/cache/` are regenerated and gitignored

## Always
- Run `.venv/Scripts/python.exe -m pytest -q` before declaring work done.
- Keep/add a test for every bug fix.
- When ingest returns empty / 0 rows, suspect a swallowed HTTP 4xx or a guessed API
  parameter FIRST — reproduce the live request and read the real response body before
  changing pipeline logic. (TED 400 and the spending batch bug were both this.)
- Pipe large command output through `tail`/`head`/`--stat`; use `pytest -q`,
  `git log --oneline`, `git diff --stat`.

## Never
- Commit anything under `data/` — write throwaway artifacts (screenshots, scratch
  files) outside the repo.
- Leave an `except` swallowing an HTTP error silently — log a count/warning so a
  broken request can't masquerade as "no data".
