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
        region = ((items[0].get("deliveryAddress") or {}).get("region")
                  or (sup.get("address") or {}).get("region"))
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


def _first(value):
    """TED v3 returns most fields as arrays; collapse to the first scalar element."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _ukr_tenderer_name(notice: dict) -> str | None:
    """Name of the first Ukrainian tenderer in a TED notice.

    `organisation-name-tenderer` is a ``{lang: [names]}`` dict whose name list is
    index-aligned with `organisation-country-tenderer`. We pick the name at the
    first position whose country is ``UKR`` (the list also includes losing
    bidders, which is acceptable for a confidence-tagged overlay).
    """
    names_by_lang = notice.get("organisation-name-tenderer") or {}
    if isinstance(names_by_lang, dict):
        names = next(iter(names_by_lang.values()), []) if names_by_lang else []
    else:
        names = names_by_lang
    names = names if isinstance(names, list) else [names]
    countries = notice.get("organisation-country-tenderer") or []
    countries = countries if isinstance(countries, list) else [countries]
    for name, country in zip(names, countries):
        if country == "UKR":
            return name
    return None


def normalize_ted(raw: list[dict]) -> pl.DataFrame:
    rows = []
    for r in raw:
        cpv = _first(r.get("classification-cpv"))
        name = _ukr_tenderer_name(r)
        # total-value is only trustworthy as EUR when the currency field confirms it.
        amount_eur = _first(r.get("total-value"))
        if _first(r.get("total-value-cur")) != "EUR":
            amount_eur = None
        rows.append({
            "ted_id": r.get("publication-number"),
            "cpv": cpv,
            "cpv_div": cpv_division(cpv),
            "winner_name": name,
            "winner_name_norm": normalize_company_name(name),
            "winner_country": "UKR" if name else None,
            "amount_eur": amount_eur,
            "region": _first(r.get("place-of-performance")),
        })
    return pl.DataFrame(rows, schema=_TED_SCHEMA)
