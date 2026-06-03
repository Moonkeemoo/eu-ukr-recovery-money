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


def pull_spending(cache_dir: Path, edrpous: list[str], max_pages: int = 50) -> list[dict]:
    """Pull spending transactions for the given recipient EDRPOUs."""
    out: list[dict] = []
    with CachedClient(cache_dir / "spending") as client:
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
    out: list[dict] = []
    with CachedClient(cache_dir / "ted") as client:
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
