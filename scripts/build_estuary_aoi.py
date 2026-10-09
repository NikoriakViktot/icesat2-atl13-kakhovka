#!/usr/bin/env python3
"""Build the Dnipro-Buh liman clip polygon from the operator's landmark points.

    python scripts/build_estuary_aoi.py [--buffer-deg 0.02] [--min-lon 31.50]

Reads  config/dnipro_estuary_points.csv   (lat,lon,label)
Writes data/aoi/dnipro_estuary.geojson    (EPSG:4326, single buffered convex hull)

The hull is clipped at ``--min-lon`` so its south-west corner does not reach far
into the open Black Sea (the westernmost landmark is a "Black Sea edge" marker).
The ATL13 refid already restricts the pull to the liman water body; this polygon
is the pass-level clip + a visual AOI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402
from shapely.geometry import MultiPoint, box, mapping  # noqa: E402

from kakhovka_altimetry.config import REPO_ROOT  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--buffer-deg", type=float, default=0.02)   # ~1.5 km
    ap.add_argument("--min-lon", type=float, default=31.50)
    args = ap.parse_args()

    pts = pd.read_csv(REPO_ROOT / "config" / "dnipro_estuary_points.csv", comment="#")
    mp = MultiPoint(list(zip(pts["lon"], pts["lat"], strict=True)))
    hull = mp.convex_hull.buffer(args.buffer_deg)
    lon_min, lat_min, lon_max, lat_max = hull.bounds
    hull = hull.intersection(box(max(lon_min, args.min_lon), lat_min, lon_max, lat_max))

    feat = {
        "type": "Feature",
        "properties": {
            "name": "Dnipro-Buh liman clip",
            "refid": 6033000138,
            "n_source_points": int(len(pts)),
            "buffer_deg": args.buffer_deg,
            "min_lon_clip": args.min_lon,
            "source": "config/dnipro_estuary_points.csv (operator landmarks)",
        },
        "geometry": mapping(hull),
    }
    out = REPO_ROOT / "data" / "aoi" / "dnipro_estuary.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"type": "FeatureCollection", "features": [feat]}, indent=1), encoding="utf-8")

    b = hull.bounds
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    print(f"  {len(pts)} points -> hull area {hull.area * 111 * 78:.0f} km^2 approx")
    print(f"  bbox lon {b[0]:.3f}..{b[2]:.3f}  lat {b[1]:.3f}..{b[3]:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
