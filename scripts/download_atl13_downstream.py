#!/usr/bin/env python3
"""Phase 3: pull ATL13 for the reference water bodies BELOW the Kakhovka dam.

    python scripts/download_atl13_downstream.py [--body SLUG] [--batch-size N] [--limit N] [--dry-run]

Bodies come from ``config/kakhovka.yaml::downstream_bodies`` (``kherson`` — lower
Dnipro; ``dnipro_estuary`` — Dnipro-Buh liman). Each has its own refid + coord,
its own curated granule list, and a spatial clip (bbox or polygon) applied to the
segment ``water_mask_pass`` and the pass-level table. Reference water bodies are
disjoint, so the Kherson/estuary bbox overlap is harmless.

Per body, writes (all git-ignored):
  data/raw/atl13/<slug>_atl13x_raw.parquet
  data/processed/<slug>_atl13_{segments,evrs,pass_levels}.parquet
  config/resources_manifest_downstream_<slug>.csv

If a body's seed list is empty/short, falls back to the union of
config/resources_manifest.csv + config/atl13_seed_granules_kherson.txt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from kakhovka_altimetry import atl13, discovery  # noqa: E402
from kakhovka_altimetry.pipeline import basic_pass_levels, within  # noqa: E402
from kakhovka_altimetry.regions import body_region  # noqa: E402
from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.io import setup_logging, write_parquet  # noqa: E402
from kakhovka_altimetry.vertical import add_evrs_columns  # noqa: E402

_FALLBACK_MIN = 50


def _read_seed(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted({
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    })


def _granules_for(cfg, body) -> list[str]:
    seed = _read_seed(body.seed_granules_file)
    if len(seed) >= _FALLBACK_MIN:
        print(f"  {len(seed)} seed granules ({body.seed_granules_file.name})")
        return seed
    fb = set(discovery.manifest_granules(cfg)) | set(
        _read_seed(cfg.repo_root / "config" / "atl13_seed_granules_kherson.txt"))
    fb = sorted(fb | set(seed))
    print(f"  seed list short ({len(seed)}) -> fallback union {len(fb)} granules "
          f"(reservoir manifest + kherson seed)")
    return fb


def _clip_geom(body):
    return body_region(body).clip_geometry()


def _pull_body(cfg, body, *, batch_size: int, limit: int | None, dry_run: bool) -> int:
    print(f"\n=== {body.slug}  refid {body.refid}  coord ({body.coord_lon:.5f}, {body.coord_lat:.5f})")
    granules = _granules_for(cfg, body)
    pd.DataFrame({"granule": granules}).to_csv(body.manifest, index=False)
    if limit:
        granules = granules[:limit]
    if dry_run or not granules:
        print("  dry run / nothing to fetch")
        return 0

    parms_base = {"atl13": {"refid": body.refid,
                            "coord": {"lon": body.coord_lon, "lat": body.coord_lat}},
                  "locks": 1}
    raw_frames, norm_frames = [], []
    n_batches = (len(granules) + batch_size - 1) // batch_size
    for i in range(0, len(granules), batch_size):
        batch = granules[i:i + batch_size]
        print(f"  atl13x batch {i // batch_size + 1}/{n_batches}: {len(batch)} granules")
        try:
            gdf = atl13.run_atl13x(cfg, batch, parms={**parms_base, "resources": list(batch)})
        except Exception as exc:  # noqa: BLE001
            print(f"    SlideRule error: {exc}", file=sys.stderr)
            continue
        if gdf is None or len(gdf) == 0:
            print("    (empty)")
            continue
        raw_frames.append(atl13.raw_frame(gdf).assign(_batch=i // batch_size))
        norm_frames.append(atl13.normalise(gdf))
        print(f"    {len(gdf)} rows")

    if not norm_frames:
        print(f"  no ATL13 rows for {body.slug} — nothing written.", file=sys.stderr)
        return 0

    write_parquet(pd.concat(raw_frames, ignore_index=True), body.raw_parquet,
                  label=f"{body.slug}_atl13x_raw")
    segments = pd.concat(norm_frames, ignore_index=True).sort_values("time").reset_index(drop=True)
    write_parquet(segments, body.segments_parquet, label=f"{body.slug}_segments")

    geom = _clip_geom(body)
    evrs = add_evrs_columns(segments, cfg)
    evrs["water_mask_pass"] = within(evrs, geom)
    write_parquet(evrs, body.evrs_parquet, label=f"{body.slug}_evrs")

    passes = basic_pass_levels(evrs, geom)
    write_parquet(passes, body.pass_levels_parquet, label=f"{body.slug}_pass_levels")

    print(f"  {len(segments)} segments, {segments['rgt'].nunique()} RGTs, "
          f"{len(passes)} beam-passes in the clip")
    if not passes.empty:
        print(f"  clip lon {passes['lon_mean'].min():.3f}..{passes['lon_mean'].max():.3f}  "
              f"lat {passes['lat_mean'].min():.3f}..{passes['lat_mean'].max():.3f}")
        print(passes.groupby("period")["n_points"].agg(passes="size", segments="sum"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--body", default=None, help="slug (default: all)")
    ap.add_argument("--batch-size", type=int, default=50)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    setup_logging()
    cfg = load_config()
    if not cfg.egg2015.available:
        print(f"EGG2015 grid missing: {cfg.egg2015.path}", file=sys.stderr)
        return 2

    bodies = cfg.downstream_bodies
    if args.body:
        bodies = [b for b in bodies if b.slug == args.body]
        if not bodies:
            print(f"unknown body {args.body!r}; have "
                  f"{[b.slug for b in cfg.downstream_bodies]}", file=sys.stderr)
            return 2
    for body in bodies:
        _pull_body(cfg, body, batch_size=args.batch_size, limit=args.limit,
                   dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
