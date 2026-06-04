import polars as pl


def join_core(contracts: pl.DataFrame, spending: pl.DataFrame) -> pl.DataFrame:
    """Left-join contracts to aggregated payments on EDRPOU. Missing pay = 0."""
    paid = (
        spending.group_by("recipient_edrpou")
        .agg(pl.col("amount_uah").sum().alias("paid_amount_uah"))
    )
    joined = contracts.join(
        paid, left_on="supplier_edrpou", right_on="recipient_edrpou", how="left"
    ).with_columns(
        pl.col("paid_amount_uah").fill_null(0),
        pl.col("amount_uah").alias("contract_amount_uah"),
    ).drop("amount_uah")
    return joined


def attach_ted_overlay(joined: pl.DataFrame, ted: pl.DataFrame) -> pl.DataFrame:
    """Attach a TED notice where winner_name_norm + cpv_div match. Confidence 1.0."""
    ted_keyed = (
        ted.select(
            pl.col("winner_name_norm").alias("supplier_name_norm"),
            "cpv_div", "ted_id", "amount_eur",
        )
        .filter(pl.col("supplier_name_norm").is_not_null() & (pl.col("supplier_name_norm") != ""))
        .sort(["amount_eur", "ted_id"], descending=[True, False], nulls_last=True)
        .unique(subset=["supplier_name_norm", "cpv_div"], keep="first", maintain_order=True)
    )
    out = joined.join(ted_keyed, on=["supplier_name_norm", "cpv_div"], how="left")
    out = out.with_columns(
        pl.when(pl.col("ted_id").is_not_null())
        .then(pl.lit(1.0))
        .otherwise(None)
        .alias("ted_match_confidence")
    )
    return out


def build_paid_by_year(contracts: pl.DataFrame, spending: pl.DataFrame) -> pl.DataFrame:
    """Payments per contract per calendar year of payment_date.

    Treasury rows carry no contractId, so payments attach to a contract via its
    supplier EDRPOU (the same supplier-level attribution as the lifetime total).
    """
    spend_year = (
        spending.with_columns(
            pl.col("payment_date").str.slice(0, 4).cast(pl.Int64).alias("year")
        )
        .group_by(["recipient_edrpou", "year"])
        .agg(pl.col("amount_uah").sum().alias("paid_uah"))
    )
    return (
        contracts.select("contract_id", "supplier_edrpou")
        .join(spend_year, left_on="supplier_edrpou", right_on="recipient_edrpou", how="inner")
        .select("contract_id", "year", "paid_uah")
    )
