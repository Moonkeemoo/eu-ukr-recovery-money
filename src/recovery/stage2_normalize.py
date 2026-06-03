import polars as pl

from .normalize_fields import cpv_division, normalize_company_name, normalize_edrpou

_PROZORRO_SCHEMA = {
    "contract_id": pl.Utf8, "cpv": pl.Utf8, "cpv_div": pl.Utf8,
    "supplier_edrpou": pl.Utf8, "supplier_name": pl.Utf8, "supplier_name_norm": pl.Utf8,
    "amount_uah": pl.Float64, "region": pl.Utf8, "redacted": pl.Boolean,
}
_SPENDING_SCHEMA = {
    "tx_id": pl.Utf8, "recipient_edrpou": pl.Utf8, "recipient_name": pl.Utf8,
    "recipient_name_norm": pl.Utf8, "amount_uah": pl.Float64,
    "payment_date": pl.Utf8, "purpose": pl.Utf8,
}
_TED_SCHEMA = {
    "ted_id": pl.Utf8, "cpv": pl.Utf8, "cpv_div": pl.Utf8,
    "winner_name": pl.Utf8, "winner_name_norm": pl.Utf8, "winner_country": pl.Utf8,
    "amount_eur": pl.Float64, "region": pl.Utf8,
}


def normalize_prozorro(raw: list[dict]) -> pl.DataFrame:
    rows = []
    for r in raw:
        suppliers = r.get("suppliers") or [{}]
        sup = suppliers[0]
        items = r.get("items") or [{}]
        cpv = (items[0].get("classification") or {}).get("id")
        region = (items[0].get("deliveryAddress") or {}).get("region")
        rows.append({
            "contract_id": r.get("contractID") or r.get("id"),
            "cpv": cpv,
            "cpv_div": cpv_division(cpv),
            "supplier_edrpou": normalize_edrpou((sup.get("identifier") or {}).get("id")),
            "supplier_name": sup.get("name"),
            "supplier_name_norm": normalize_company_name(sup.get("name")),
            "amount_uah": (r.get("value") or {}).get("amount"),
            "region": region,
            "redacted": bool(r.get("redacted", False)),
        })
    return pl.DataFrame(rows, schema=_PROZORRO_SCHEMA)


def normalize_spending(raw: list[dict]) -> pl.DataFrame:
    rows = []
    for r in raw:
        name = r.get("recipt_name")  # "recipt_" is the upstream API spelling, not a local typo
        rows.append({
            "tx_id": str(r["id"]) if r.get("id") is not None else None,
            "recipient_edrpou": normalize_edrpou(r.get("recipt_edrpou")),  # upstream spelling
            "recipient_name": name,
            "recipient_name_norm": normalize_company_name(name),
            "amount_uah": r.get("amount"),
            "payment_date": r.get("trans_date"),
            "purpose": r.get("payment_details"),
        })
    return pl.DataFrame(rows, schema=_SPENDING_SCHEMA)


def normalize_ted(raw: list[dict]) -> pl.DataFrame:
    rows = []
    for r in raw:
        cpv = r.get("classification-cpv")
        name = r.get("winner-name")
        rows.append({
            "ted_id": r.get("publication-number"),
            "cpv": cpv,
            "cpv_div": cpv_division(cpv),
            "winner_name": name,
            "winner_name_norm": normalize_company_name(name),
            "winner_country": r.get("winner-country"),
            "amount_eur": r.get("value"),
            "region": r.get("place-of-performance"),
        })
    return pl.DataFrame(rows, schema=_TED_SCHEMA)
