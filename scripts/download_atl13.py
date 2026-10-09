#!/usr/bin/env python3
"""Step 1: discover ATL13 granules and pull water-surface segments via SlideRule.

    python scripts/download_atl13.py [--refresh] [--limit N] [--batch-size N] [--dry-run]

Writes:
  * config/resources_manifest.csv        (reproducibility manifest)
  * data/processed/kakhovka_atl13_segments.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from kakhovka_altimetry import atl13, discovery, pipeline  # noqa: E402
from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.io import setup_logging, write_parquet  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true",
                    help="run a live CMR search and merge new granules into the manifest")
    ap.add_argument("--limit", type=int, default=None,
                    help="process only the first N granules (smoke test)")
    ap.add_argument("--batch-size", type=int, default=50,
                    help="granules per SlideRule request")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the manifest but do not call SlideRule")
    args = ap.parse_args()

    setup_logging()
    cfg = load_config()

    manifest = discovery.build_manifest(cfg, include_cmr=args.refresh, write=True)
    granules = list(manifest.sort_values("acquisition_time")["granule"])
    print(f"manifest: {len(granules)} granules "
          f"({(manifest['source'] != 'seed').sum()} from CMR)")

    if args.limit:
        granules = granules[: args.limit]
    if args.dry_run:
        print("dry run - stopping before SlideRule")
        return 0

    raw_frames: list[pd.DataFrame] = []
    norm_frames: list[pd.DataFrame] = []
    n_batches = (len(granules) + args.batch_size - 1) // args.batch_size
    for i in range(0, len(granules), args.batch_size):
        batch = granules[i : i + args.batch_size]
        print(f"  atl13x batch {i // args.batch_size + 1}/{n_batches}: {len(batch)} granules")
        gdf = atl13.run_atl13x(cfg, batch)
        if gdf is None or len(gdf) == 0:
            print("    (empty)")
            continue
        raw_frames.append(atl13.raw_frame(gdf).assign(_batch=i // args.batch_size))
        norm_frames.append(atl13.normalise(gdf))
        print(f"    {len(gdf)} rows")

    if not norm_frames:
        print("no ATL13 rows returned by SlideRule", file=sys.stderr)
        return 1

    # 1. verbatim SlideRule return
    raw = pd.concat(raw_frames, ignore_index=True)
    write_parquet(raw, cfg.raw_atl13x_parquet, label="atl13x_raw")

    # normalised intermediate -> segments; attach granule name via (rgt, cycle).
    segments = pd.concat(norm_frames, ignore_index=True)
    gmap = pipeline.granule_lookup(manifest["granule"])
    segments["granule"] = [
        gmap.get((int(r), int(c))) if pd.notna(r) and pd.notna(c) else None
        for r, c in zip(segments["rgt"], segments["cycle"], strict=False)
    ]
    segments = segments.sort_values("time").reset_index(drop=True)
    write_parquet(segments, cfg.segments_parquet, label="segments")
    print(segments.head())
    print(f"\n{len(segments)} segments, "
          f"{segments['time'].dt.date.nunique()} distinct dates, "
          f"{segments['rgt'].nunique()} RGTs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
