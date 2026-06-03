from pathlib import Path

import duckdb


def _conn(out_dir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    parquet_path = str(Path(out_dir) / "chain.parquet").replace("\\", "/")
    con.execute(f"CREATE VIEW chain AS SELECT * FROM read_parquet('{parquet_path}')")
    return con


def _where(sector: str | None, region: str | None) -> tuple[str, list]:
    clauses, params = [], []
    if sector:
        clauses.append("cpv_div = ?")
        params.append(sector)
    if region:
        clauses.append("region = ?")
        params.append(region)
    return (("WHERE " + " AND ".join(clauses)) if clauses else ""), params


def kpi(out_dir: Path, sector: str | None = None, region: str | None = None) -> dict:
    con = _conn(out_dir)
    where, params = _where(sector, region)
    row = con.execute(
        f"""SELECT
              COALESCE(SUM(contract_amount_uah), 0) AS contracted,
              COALESCE(SUM(paid_amount_uah), 0) AS paid,
              COALESCE(SUM(ted_amount_eur), 0) AS announced_eur,
              COALESCE(SUM(CASE WHEN state = 'contract_no_payment' THEN 1 ELSE 0 END), 0) AS breaks
            FROM chain {where}""",
        params,
    ).fetchone()
    con.close()
    return {
        "contracted_uah": int(row[0]), "paid_uah": int(row[1]),
        "announced_eur": int(row[2]), "breaks": int(row[3]),
    }


def sankey(out_dir: Path, sector: str | None = None, region: str | None = None) -> dict:
    con = _conn(out_dir)
    where, params = _where(sector, region)
    row = con.execute(
        f"""SELECT
              COALESCE(SUM(ted_amount_eur), 0),
              COALESCE(SUM(contract_amount_uah), 0),
              COALESCE(SUM(paid_amount_uah), 0)
            FROM chain {where}""",
        params,
    ).fetchone()
    con.close()
    nodes = [{"name": "Оголошено (TED)"}, {"name": "Законтрактовано"}, {"name": "Виплачено"}]
    links = [
        {"source": 0, "target": 1, "value": int(row[1])},
        {"source": 1, "target": 2, "value": int(row[2])},
    ]
    return {"nodes": nodes, "links": links, "announced_eur": int(row[0])}


def supplier(out_dir: Path, edrpou: str) -> dict:
    con = _conn(out_dir)
    rows = con.execute(
        "SELECT contract_id, cpv_div, region, contract_amount_uah, paid_amount_uah, "
        "ted_id, state FROM chain WHERE supplier_edrpou = ?",
        [edrpou],
    ).to_arrow_table().to_pylist()
    con.close()
    return {"edrpou": edrpou, "contracts": rows}


def gaps(out_dir: Path, gap_type: str = "contract_no_payment") -> list[dict]:
    con = _conn(out_dir)
    rows = con.execute(
        "SELECT contract_id, supplier_name, cpv_div, region, contract_amount_uah, state "
        "FROM chain WHERE state = ?",
        [gap_type],
    ).to_arrow_table().to_pylist()
    con.close()
    return rows


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
