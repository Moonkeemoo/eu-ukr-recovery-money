from pathlib import Path

import duckdb


def _conn(out_dir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    parquet_path = str(Path(out_dir) / "chain.parquet").replace("\\", "/")
    con.execute(f"CREATE VIEW chain AS SELECT * FROM read_parquet('{parquet_path}')")
    return con


def _scope(out_dir, sector=None, region=None, contract_year=None, payment_year=None):
    """Return (from_sql, where_sql, params): a relation aliased `q` (with paid_amount_uah
    swapped to the selected payment year when set), an outer WHERE clause (possibly ''), and
    bound params. Compose in each query as: FROM {from_sql} {where_sql}."""
    clauses, where_params = [], []
    if sector:
        clauses.append("q.cpv_div = ?"); where_params.append(sector)
    if region:
        clauses.append("q.region = ?"); where_params.append(region)
    if contract_year:
        clauses.append("q.contract_year = ?"); where_params.append(int(contract_year))
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    pby_path = Path(out_dir) / "paid_by_year.parquet"
    if payment_year and pby_path.exists():  # ignore the filter if the side table isn't built yet
        pby = str(pby_path).replace("\\", "/")
        from_sql = (
            "(SELECT c.* REPLACE (py.paid_uah AS paid_amount_uah) FROM chain c "
            "JOIN (SELECT contract_id, SUM(paid_uah) AS paid_uah "
            f"FROM read_parquet('{pby}') WHERE year = ? GROUP BY contract_id) py "
            "ON c.contract_id = py.contract_id) q"
        )
        params = [int(payment_year)] + where_params  # subquery's year ? precedes the WHERE ?s
    else:
        from_sql = "chain q"
        params = where_params
    return from_sql, where_sql, params


def kpi(out_dir: Path, sector: str | None = None, region: str | None = None,
        contract_year: int | None = None, payment_year: int | None = None) -> dict:
    con = _conn(out_dir)
    from_sql, where_sql, params = _scope(out_dir, sector, region, contract_year, payment_year)
    row = con.execute(
        f"""SELECT
              COALESCE(SUM(contract_amount_uah), 0) AS contracted,
              COALESCE(SUM(paid_amount_uah), 0) AS paid,
              COALESCE(SUM(ted_amount_eur), 0) AS announced_eur,
              COALESCE(SUM(CASE WHEN state = 'contract_no_payment' THEN 1 ELSE 0 END), 0) AS breaks
            FROM {from_sql} {where_sql}""",
        params,
    ).fetchone()
    con.close()
    return {
        "contracted_uah": int(row[0]), "paid_uah": int(row[1]),
        "announced_eur": int(row[2]), "breaks": int(row[3]),
    }


def sankey(out_dir: Path, sector: str | None = None, region: str | None = None,
           contract_year: int | None = None, payment_year: int | None = None) -> dict:
    con = _conn(out_dir)
    from_sql, where_sql, params = _scope(out_dir, sector, region, contract_year, payment_year)
    row = con.execute(
        f"""SELECT
              COALESCE(SUM(ted_amount_eur), 0),
              COALESCE(SUM(contract_amount_uah), 0),
              COALESCE(SUM(paid_amount_uah), 0)
            FROM {from_sql} {where_sql}""",
        params,
    ).fetchone()
    con.close()
    nodes = [{"name": "Оголошено (TED)"}, {"name": "Законтрактовано"}, {"name": "Надходження постачальникам"}]
    links = [
        {"source": 0, "target": 1, "value": int(row[1])},
        {"source": 1, "target": 2, "value": int(row[2])},
    ]
    return {"nodes": nodes, "links": links, "announced_eur": int(row[0])}


def supplier(out_dir: Path, edrpou: str) -> dict:
    con = _conn(out_dir)
    rows = con.execute(
        "SELECT contract_id, cpv_div, region, contract_amount_uah, paid_amount_uah, "
        "ted_id, ted_match_confidence, state FROM chain WHERE supplier_edrpou = ?",
        [edrpou],
    ).to_arrow_table().to_pylist()
    con.close()
    return {"edrpou": edrpou, "contracts": rows}


def gaps(out_dir: Path, gap_type: str = "contract_no_payment",
         sector: str | None = None, region: str | None = None,
         contract_year: int | None = None, payment_year: int | None = None) -> list[dict]:
    con = _conn(out_dir)
    from_sql, where_sql, params = _scope(out_dir, sector, region, contract_year, payment_year)
    state_clause = "AND q.state = ?" if where_sql else "WHERE q.state = ?"
    result = con.execute(
        "SELECT contract_id, supplier_name, supplier_edrpou, cpv_div, region, "
        f"contract_amount_uah, state FROM {from_sql} {where_sql} {state_clause}",
        params + [gap_type],
    ).to_arrow_table().to_pylist()
    con.close()
    return result


def funnel(out_dir: Path) -> list[dict]:
    con = duckdb.connect(":memory:")
    rows = con.execute(
        "SELECT * FROM read_parquet(?)",
        [str(Path(out_dir) / "funnel.parquet")],
    ).to_arrow_table().to_pylist()
    con.close()
    return rows


def regions(out_dir: Path) -> list[str]:
    con = _conn(out_dir)
    rows = con.execute(
        "SELECT DISTINCT region FROM chain "
        "WHERE region IS NOT NULL AND region <> '' ORDER BY region"
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def breakdown(out_dir: Path, sector: str | None = None, region: str | None = None,
              contract_year: int | None = None, payment_year: int | None = None) -> list[dict]:
    con = _conn(out_dir)
    from_sql, where_sql, params = _scope(out_dir, sector, region, contract_year, payment_year)
    rows = con.execute(
        f"""SELECT state,
              COUNT(*) AS cnt,
              COALESCE(SUM(contract_amount_uah), 0) AS contracted,
              COALESCE(SUM(paid_amount_uah), 0) AS paid
            FROM {from_sql} {where_sql}
            GROUP BY state ORDER BY state""",
        params,
    ).fetchall()
    con.close()
    return [
        {"state": r[0], "count": int(r[1]),
         "contracted_uah": int(r[2]), "paid_uah": int(r[3])}
        for r in rows
    ]


def top(out_dir: Path, by: str, sector: str | None = None,
        region: str | None = None, contract_year: int | None = None,
        payment_year: int | None = None, limit: int = 10) -> list[dict]:
    if by not in ("supplier", "region"):
        raise ValueError(f"invalid 'by': {by!r} (expected 'supplier' or 'region')")
    con = _conn(out_dir)
    from_sql, where_sql, params = _scope(out_dir, sector, region, contract_year, payment_year)
    if by == "supplier":
        rows = con.execute(
            f"""SELECT supplier_edrpou, any_value(supplier_name) AS name,
                  COALESCE(SUM(contract_amount_uah), 0) AS contracted,
                  COALESCE(SUM(paid_amount_uah), 0) AS paid,
                  COUNT(*) AS n
                FROM {from_sql} {where_sql}
                GROUP BY supplier_edrpou
                ORDER BY contracted DESC LIMIT ?""",
            params + [limit],
        ).fetchall()
        con.close()
        return [
            {"edrpou": r[0], "supplier_name": r[1], "contracted_uah": int(r[2]),
             "paid_uah": int(r[3]), "contracts": int(r[4])}
            for r in rows
        ]
    rows = con.execute(
        f"""SELECT region,
              COALESCE(SUM(contract_amount_uah), 0) AS contracted,
              COALESCE(SUM(paid_amount_uah), 0) AS paid,
              COUNT(*) AS n
            FROM {from_sql} {where_sql}
            GROUP BY region
            ORDER BY contracted DESC LIMIT ?""",
        params + [limit],
    ).fetchall()
    con.close()
    return [
        {"region": r[0], "contracted_uah": int(r[1]),
         "paid_uah": int(r[2]), "contracts": int(r[3])}
        for r in rows
    ]


def years(out_dir: Path) -> dict:
    con = _conn(out_dir)
    crows = con.execute(
        "SELECT DISTINCT contract_year FROM chain "
        "WHERE contract_year IS NOT NULL ORDER BY contract_year DESC"
    ).fetchall()
    payment_years: list[int] = []
    pby = Path(out_dir) / "paid_by_year.parquet"
    if pby.exists():
        path = str(pby).replace("\\", "/")
        prows = con.execute(
            f"SELECT DISTINCT year FROM read_parquet('{path}') "
            "WHERE year IS NOT NULL ORDER BY year DESC"
        ).fetchall()
        payment_years = [int(r[0]) for r in prows]
    con.close()
    return {"contract_years": [int(r[0]) for r in crows], "payment_years": payment_years}
