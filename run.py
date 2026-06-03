import argparse

from recovery import config
from recovery import stage1_ingest as stage1
from recovery.stage2_normalize import normalize_prozorro, normalize_spending, normalize_ted
from recovery.stage3_join import join_core, attach_ted_overlay
from recovery.stage4_chain import build_chain, build_funnel


def main(target: int = config.PROZORRO_TARGET, scan_cap: int = config.PROZORRO_SCAN_CAP) -> None:
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_pz = stage1.pull_prozorro(cache_dir=config.CACHE_DIR, target=target, scan_cap=scan_cap)
    contracts = normalize_prozorro(raw_pz)

    edrpous = contracts["supplier_edrpou"].drop_nulls().unique().to_list()
    raw_sp = stage1.pull_spending(cache_dir=config.CACHE_DIR, edrpous=edrpous)
    spending = normalize_spending(raw_sp)

    try:
        raw_ted = stage1.pull_ted(cache_dir=config.CACHE_DIR)
        ted = normalize_ted(raw_ted)
    except Exception as exc:  # TED v3 is best-effort; keep the pipeline running without it
        print(f"TED ingest skipped (non-fatal): {exc}")
        ted = normalize_ted([])

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
    parser.add_argument("--target", type=int, default=config.PROZORRO_TARGET,
                        help="stop after this many in-scope contracts")
    parser.add_argument("--scan-cap", type=int, default=config.PROZORRO_SCAN_CAP,
                        help="stop after scanning this many feed stubs")
    args = parser.parse_args()
    main(target=args.target, scan_cap=args.scan_cap)
