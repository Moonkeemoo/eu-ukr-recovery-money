from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from recovery import config, queries

app = FastAPI(title="eu-ukr-recovery-money")
WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@app.get("/api/kpi")
def get_kpi(sector: str | None = None, region: str | None = None):
    return queries.kpi(config.OUT_DIR, sector=sector, region=region)


@app.get("/api/sankey")
def get_sankey(sector: str | None = None, region: str | None = None):
    return queries.sankey(config.OUT_DIR, sector=sector, region=region)


@app.get("/api/supplier/{edrpou}")
def get_supplier(edrpou: str):
    return queries.supplier(config.OUT_DIR, edrpou)


@app.get("/api/gaps")
def get_gaps(gap_type: str = Query("contract_no_payment", alias="type")):
    return queries.gaps(config.OUT_DIR, gap_type=gap_type)


@app.get("/api/funnel")
def get_funnel():
    return queries.funnel(config.OUT_DIR)


@app.get("/api/regions")
def get_regions():
    return queries.regions(config.OUT_DIR)


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
