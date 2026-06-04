"""Seed a small, realistic DEMO dataset into data/out/ so the UI can be explored
without a live API pull.

This is NOT real data. The live ingest (run.py) needs the TED v3 / spending.gov.ua
request formats verified against the live APIs first (see README "API field names").
Run:  python scripts/seed_demo.py   then   uvicorn api.app:app
"""

import polars as pl

from recovery import config

config.OUT_DIR.mkdir(parents=True, exist_ok=True)

rows = [
    # full chains: contracted + paid + a matched TED notice
    dict(contract_id="UA-2025-09-01-000001", supplier_edrpou="31725604",
         supplier_name='ТОВ "Шляхбуд"', cpv_div="45", region="Київська область",
         contract_amount_uah=18_500_000, paid_amount_uah=14_200_000,
         ted_amount_eur=420_000, ted_id="00654321-2025",
         ted_match_confidence=1.0, state="full"),
    dict(contract_id="UA-2025-07-14-000245", supplier_edrpou="40293841",
         supplier_name='ПрАТ "Енергомонтаж"', cpv_div="09", region="Львівська область",
         contract_amount_uah=33_100_000, paid_amount_uah=33_100_000,
         ted_amount_eur=810_000, ted_id="00712233-2025",
         ted_match_confidence=1.0, state="full"),
    # paid, but no TED notice on the left (payment_no_ted)
    dict(contract_id="UA-2025-05-22-000087", supplier_edrpou="33341264",
         supplier_name='ТОВ "Міст-Інжиніринг"', cpv_div="71", region="Одеська область",
         contract_amount_uah=7_800_000, paid_amount_uah=5_900_000,
         ted_amount_eur=None, ted_id=None, ted_match_confidence=None,
         state="payment_no_ted"),
    dict(contract_id="UA-2025-08-03-000512", supplier_edrpou="21560011",
         supplier_name='ДП "Укравтодор-Південь"', cpv_div="45", region="Миколаївська область",
         contract_amount_uah=52_000_000, paid_amount_uah=48_750_000,
         ted_amount_eur=None, ted_id=None, ted_match_confidence=None,
         state="payment_no_ted"),
    dict(contract_id="UA-2025-06-19-000333", supplier_edrpou="38217450",
         supplier_name='ТОВ "Тепломережі Плюс"', cpv_div="09", region="Харківська область",
         contract_amount_uah=12_300_000, paid_amount_uah=9_100_000,
         ted_amount_eur=None, ted_id=None, ted_match_confidence=None,
         state="payment_no_ted"),
    # contracted but never paid: the "breaks" the product is built to surface
    dict(contract_id="UA-2025-09-28-000901", supplier_edrpou="44120876",
         supplier_name='ТОВ "БудКапітал"', cpv_div="45", region="Донецька область",
         contract_amount_uah=64_200_000, paid_amount_uah=0,
         ted_amount_eur=None, ted_id=None, ted_match_confidence=None,
         state="contract_no_payment"),
    dict(contract_id="UA-2025-10-05-001120", supplier_edrpou="39845102",
         supplier_name='ПП "Електро-Транс"', cpv_div="34", region="Дніпропетровська область",
         contract_amount_uah=28_900_000, paid_amount_uah=0,
         ted_amount_eur=None, ted_id=None, ted_match_confidence=None,
         state="contract_no_payment"),
    dict(contract_id="UA-2025-08-30-000777", supplier_edrpou="41003922",
         supplier_name='ТОВ "Проектний Інститут-7"', cpv_div="71", region="Запорізька область",
         contract_amount_uah=4_500_000, paid_amount_uah=0,
         ted_amount_eur=None, ted_id=None, ted_match_confidence=None,
         state="contract_no_payment"),
    dict(contract_id="UA-2025-07-01-000064", supplier_edrpou="31725604",
         supplier_name='ТОВ "Шляхбуд"', cpv_div="34", region="Київська область",
         contract_amount_uah=9_700_000, paid_amount_uah=0,
         ted_amount_eur=None, ted_id=None, ted_match_confidence=None,
         state="contract_no_payment"),
]
pl.DataFrame(rows).write_parquet(config.OUT_DIR / "chain.parquet")

n = len(rows)
paid = sum(1 for r in rows if r["paid_amount_uah"] > 0)
ted = sum(1 for r in rows if r["ted_id"])
pl.DataFrame([
    {"step": "contracts", "count": n},
    {"step": "with_payment", "count": paid},
    {"step": "with_ted_overlay", "count": ted},
]).write_parquet(config.OUT_DIR / "funnel.parquet")

print(f"Seeded {n} demo chain rows ({paid} paid, {ted} with TED, "
      f"{n - paid} breaks) -> {config.OUT_DIR}")
