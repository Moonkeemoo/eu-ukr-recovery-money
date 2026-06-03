import argparse

from recovery import config
from recovery import stage1_ingest as stage1
from recovery.stage2_normalize import normalize_prozorro, normalize_spending, normalize_ted
from recovery.stage3_join import join_core, attach_ted_overlay
from recovery.stage4_chain import build_chain, build_funnel


def main(max_pages: int = 50) -> None:
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_pz = stage1.pull_prozorro(cache_dir=config.CACHE_DIR, max_pages=max_pages)
    contracts = normalize_prozorro(raw_pz)

    edrpous = contracts["supplier_edrpou"].drop_nulls().unique().to_list()
    raw_sp = stage1.pull_spending(cache_dir=config.CACHE_DIR, edrpous=edrpous, max_pages=max_pages)
    spending = normalize_spending(raw_sp)

    raw_ted = stage1.pull_ted(cache_dir=config.CACHE_DIR, max_pages=max_pages)
    ted = normalize_ted(raw_ted)

    contracts.write_parquet(config.OUT_DIR / "prozorro_contracts.parquet")
    spending.write_parquet(config.OUT_DIR / "spending_tx.parquet")
    ted.write_parquet(config.OUT_DIR / "ted_notices.parquet")

    joined = attach_ted_overlay(join_core(contracts, spending), ted)
    chain = build_chain(joined)
    funnel = build_funnel(joined)

    chain.write_parquet(config.OUT_DIR / "chain.parquet")
    funnel.write_parquet(config.OUT_DIR / "funnel.parquet")
    print(f"Wrote {chain.height} chain rows to {config.OUT_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=50)
    args = parser.parse_args()
    main(max_pages=args.max_pages)
