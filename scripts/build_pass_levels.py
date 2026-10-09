#!/usr/bin/env python3
"""Step 3: aggregate EVRS segments to one water-surface elevation per pass.

    python scripts/build_pass_levels.py

Reads  data/processed/kakhovka_atl13_evrs.parquet
Writes data/processed/kakhovka_atl13_pass_levels.parquet
       outputs/tables/atl13_pass_levels.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kakhovka_altimetry.aggregate import pass_level_table  # noqa: E402
from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.io import read_parquet, setup_logging, write_parquet  # noqa: E402


def main() -> int:
    setup_logging()
    cfg = load_config()

    evrs = read_parquet(cfg.evrs_parquet)
    passes = pass_level_table(evrs, cfg)

    n_pass = len(passes)
    n_ok = int(passes["qc_pass"].sum())
    print(f"{n_pass} passes, {n_ok} pass QC ({n_pass - n_ok} rejected)")
    if n_pass:
        print("\nby period:\n",
              passes.groupby("period")["qc_pass"].agg(size="size", pass_qc="sum"))
        print("\nby year:\n",
              passes.groupby("year")["qc_pass"].agg(size="size", pass_qc="sum"))
        rej = passes.loc[~passes["qc_pass"], "qc_flags"]
        if not rej.empty and rej.str.len().gt(0).any():
            print("\nrejection reasons:\n",
                  rej[rej.str.len() > 0].str.get_dummies("|").sum().sort_values(ascending=False))

    write_parquet(passes, cfg.pass_levels_parquet, label="pass_levels")
    cfg.tables_dir.mkdir(parents=True, exist_ok=True)
    passes.to_csv(cfg.tables_dir / "atl13_pass_levels.csv", index=False)
    print(f"\nwrote {cfg.tables_dir / 'atl13_pass_levels.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
