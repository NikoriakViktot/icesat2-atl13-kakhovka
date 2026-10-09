#!/usr/bin/env python3
"""Step 2: add the EVRS vertical chain + water mask + regime to the segments.

    python scripts/build_evrs.py

Reads  data/processed/kakhovka_atl13_segments.parquet
Writes data/processed/kakhovka_atl13_evrs.parquet
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.io import read_parquet, setup_logging, write_parquet  # noqa: E402
from kakhovka_altimetry.vertical import add_evrs_columns  # noqa: E402
from kakhovka_altimetry.water_filter import add_water_mask_column  # noqa: E402


def main() -> int:
    setup_logging()
    cfg = load_config()

    if not cfg.egg2015.available:
        print(f"EGG2015 grid missing: {cfg.egg2015.path}\n"
              f"Set the path in config/vertical_datums.yaml and place the grid there.",
              file=sys.stderr)
        return 2

    segments = read_parquet(cfg.segments_parquet)
    df = add_water_mask_column(segments, cfg)
    df = add_evrs_columns(df, cfg)

    diff = df["egm2008_minus_evrs_m"].dropna()
    print(f"egm2008_minus_evrs_m: mean={diff.mean():.3f} m  std={diff.std():.3f} m  "
          f"[{diff.min():.3f}, {diff.max():.3f}]  (expect small & smooth)")
    print(df["period"].value_counts())
    print("on-water segments:", int(df["water_mask_pass"].sum()), "/", len(df))

    write_parquet(df, cfg.evrs_parquet, label="evrs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
