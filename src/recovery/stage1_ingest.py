from datetime import date, timedelta
from pathlib import Path

import httpx

from . import config
from .clients import CachedClient


def pull_prozorro(cache_dir: Path, target: int = config.PROZORRO_TARGET,
                  scan_cap: int = config.PROZORRO_SCAN_CAP) -> list[dict]:
    """Walk the ProZorro contracts change-feed newest-first, fetch each full contract,
    and keep those with a reconstruction-CPV item. Stops at `target` kept or `scan_cap`
    scanned."""
    out: list[dict] = []
    scanned = 0
    offset = None
    with CachedClient(cache_dir / "prozorro") as client:
        while scanned < scan_cap and len(out) < target:
            params = {"descending": "1"}
            if offset:
                params["offset"] = offset
            feed = client.get_json(f"{config.PROZORRO_OCDS}/contracts", params=params)
            stubs = feed.get("data") or []
            if not stubs:
                break
            for stub in stubs:
                if scanned >= scan_cap or len(out) >= target:
                    break
                cid = stub.get("id")
                if not cid:
                    continue
                scanned += 1
                try:
                    rec = client.get_json(f"{config.PROZORRO_OCDS}/contracts/{cid}")
                except httpx.HTTPError:
                    continue  # skip a contract that fails to fetch; keep walking
                data = rec.get("data") or {}
                items = data.get("items") or []
                if any(config.cpv_in_scope((it.get("classification") or {}).get("id")) for it in items):
                    out.append(data)
            new_offset = (feed.get("next_page") or {}).get("offset")
            if not new_offset or new_offset == offset:
                break
            offset = new_offset
    print(f"ProZorro: scanned {scanned} contracts, kept {len(out)} in-scope")
    return out


def _quarter_windows(today: date, months: int, window_days: int) -> list[tuple[str, str]]:
    """Contiguous (startdate, enddate) ISO pairs covering the last `months`, each spanning
    at most `window_days` days (the spending API caps a query at 92 days)."""
    # months*30 ≈ 360 days — a deliberate approximation; fine for a bounded recent-data sample
    start_all = today - timedelta(days=months * 30)
    windows: list[tuple[str, str]] = []
    cur_end = today
    while cur_end > start_all:
        cur_start = max(start_all, cur_end - timedelta(days=window_days))
        windows.append((cur_start.isoformat(), cur_end.isoformat()))
        cur_end = cur_start - timedelta(days=1)
    return windows


def pull_spending(cache_dir: Path, edrpous: list[str],
                  batch: int = config.SPENDING_BATCH,
                  window_days: int = config.SPENDING_WINDOW_DAYS,
                  months: int = config.WINDOW_MONTHS,
                  today: date | None = None) -> list[dict]:
    """Pull treasury transactions for the given recipient EDRPOUs, batching EDRPOUs into
    `recipt_edrpous` and chunking the date range into <=`window_days` windows."""
    if today is None:
        today = date.today()
    uniq = sorted({e for e in edrpous if e})
    windows = _quarter_windows(today, months, window_days)
    out: list[dict] = []
    skipped = 0
    last_error = ""
    with CachedClient(cache_dir / "spending") as client:
        for i in range(0, len(uniq), batch):
            recipt = ",".join(uniq[i:i + batch])
            for start, end in windows:
                try:
                    rows = client.get_json(
                        f"{config.SPENDING_API}/v2/api/transactions/",
                        params={"recipt_edrpous": recipt, "startdate": start, "enddate": end},
                    )
                except httpx.HTTPError as exc:
                    # Keep going, but never silently: a swallowed batch error once
                    # hid the fact that batch>10 always 400s and produced 0 rows.
                    skipped += 1
                    last_error = str(exc)
                    continue
                if isinstance(rows, list):
                    out.extend(rows)
    msg = f"spending: queried {len(uniq)} EDRPOUs over {len(windows)} windows, {len(out)} rows"
    if skipped:
        msg += f" — WARNING: {skipped} request(s) failed and were skipped (last: {last_error})"
    print(msg)
    return out


def pull_ted(cache_dir: Path, max_pages: int = 50) -> list[dict]:
    """Pull TED notices for reconstruction CPVs won by Ukrainian entities.

    Uses the v3 expert-search POST endpoint. The reconstruction-CPV firehose
    spans the whole EU, but the project's join only matches Ukrainian suppliers,
    so the query is scoped to `winner-country=UKR` — the overlay only carries
    notices that can realistically link to a ProZorro contract.
    """
    out: list[dict] = []
    with CachedClient(cache_dir / "ted") as client:
        cpv_expr = " OR ".join(f"classification-cpv={d}*" for d in config.CPV_DIVISIONS)
        query = f"({cpv_expr}) AND winner-country=UKR"
        page = 1
        while page <= max_pages:
            data = client.post_json(
                config.TED_SEARCH,
                {"query": query, "fields": list(config.TED_FIELDS),
                 "page": page, "limit": 100},
            )
            rows = data.get("notices") or []
            if not rows:
                break
            out.extend(rows)
            page += 1
    return out
