#!/usr/bin/env python3
"""Phase 2 (NOT part of V1): match ICESat-2 pass levels to gauge stage series and
estimate the empirical vertical alignment constant.

    python scripts/match_gauges.py [--all-passes]

Reads  data/processed/kakhovka_atl13_pass_levels.parquet
       gauge parquet via config/gauges.yaml (reservoir_parquet format)
Writes data/processed/kakhovka_atl13_gauge_matchups.parquet
       outputs/tables/gauge_icesat_matchups.csv
       outputs/tables/gauge_vertical_alignment.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.datum import estimate_empirical_alignment, summarise  # noqa: E402
from kakhovka_altimetry.gauges import load_gauge_observations  # noqa: E402
from kakhovka_altimetry.io import read_parquet, setup_logging, write_parquet  # noqa: E402
from kakhovka_altimetry.matchup import build_matchups  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all-passes", action="store_true",
                    help="include passes that failed QC")
    args = ap.parse_args()

    setup_logging()
    cfg = load_config()

    passes = read_parquet(cfg.pass_levels_parquet)
    obs = load_gauge_observations(cfg)
    if obs.empty:
        print("no gauge observations found - check config/gauges.yaml `raw.dir` "
              "and the station list.", file=sys.stderr)
        return 2

    matchups = build_matchups(passes, obs, cfg, qc_only=not args.all_passes)
    write_parquet(matchups, cfg.gauge_matchups_parquet, label="gauge_matchups")

    tables_dir = cfg.repo_root / "outputs" / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    matchups.to_csv(tables_dir / "gauge_icesat_matchups.csv", index=False)

    if matchups.empty:
        print("no matchups within the configured time/distance windows")
        return 0

    alignment = estimate_empirical_alignment(matchups, cfg)
    alignment.to_csv(tables_dir / "gauge_vertical_alignment.csv", index=False)

    print(f"{len(matchups)} matchups")
    print("\nempirical vertical alignment constant:\n",
          alignment.to_string(index=False))
    print("\n" + summarise(alignment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
