import polars as pl


def build_chain(joined: pl.DataFrame) -> pl.DataFrame:
    # Note: the spec's `payment_no_contract` state is intentionally not produced here.
    # Stage 3 is a contracts-left-join, so spending rows with no matching contract never
    # reach `joined`; those are surfaced as gaps elsewhere, not in the chain.
    state = (
        pl.when((pl.col("paid_amount_uah") > 0) & pl.col("ted_id").is_not_null())
        .then(pl.lit("full"))
        .when(pl.col("paid_amount_uah") == 0)
        .then(pl.lit("contract_no_payment"))
        .otherwise(pl.lit("payment_no_ted"))
    )
    return joined.with_columns(state.alias("state")).select(
        "contract_id", "supplier_edrpou", "supplier_name", "cpv_div", "region",
        "contract_year",
        "contract_amount_uah", "paid_amount_uah",
        pl.col("amount_eur").alias("ted_amount_eur"),
        "ted_id", "ted_match_confidence", "state",
    )


def build_funnel(joined: pl.DataFrame) -> pl.DataFrame:
    return pl.DataFrame([
        {"step": "contracts", "count": joined.height},
        {"step": "with_payment", "count": joined.filter(pl.col("paid_amount_uah") > 0).height},
        {"step": "with_ted_overlay", "count": joined.filter(pl.col("ted_id").is_not_null()).height},
    ])
