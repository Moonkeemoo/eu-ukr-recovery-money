from pathlib import Path

from . import config
from .clients import CachedClient


def pull_prozorro(cache_dir: Path, max_pages: int = 50) -> list[dict]:
    """Pull ProZorro OCDS contracts, filtered to reconstruction CPVs."""
    out: list[dict] = []
    with CachedClient(cache_dir / "prozorro") as client:
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
