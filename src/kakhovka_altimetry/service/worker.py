"""The job runner: discover -> acquire -> process -> load, for ATL13 / ATL08 / ATL03.

    python -m kakhovka_altimetry.service.worker --region kakhovka [--product ATL08]
        [--start D] [--end D] [--cmr] [--limit N] [--compare cop30 fabdem]
        [--dem-res 100]                         # create + run one job synchronously
    rq worker icesat2                           # consume jobs queued by the API

Every stage records itself in ``icesat2.jobs``. Granules already ``loaded``/``empty``
for the (region, product) are skipped at discovery, so a repeated job only pulls
new passes. ``process`` also runs the optional reference-DEM comparison
(``compare``) and grids ICESat-2 points into COG rasters (``dem``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import tempfile
import time
import traceback
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .. import atl13, dem, pipeline, products
from ..config import Config, load_config
from ..regions import EGG2015, Region, configured_regions, region_from_dict
from ..vertical import GeoidGrid, load_geoid, load_geoid_file
from . import storage
from .repository import Repository
from .settings import Settings, get_settings

log = logging.getLogger("kakhovka_altimetry.service")


def resolve_region(cfg: Config, params: dict[str, Any],
                   repo: Repository | None = None) -> Region:
    """An inline region from the request, a configured one, or a registered one."""
    if params.get("region"):
        return region_from_dict(params["region"])
    slug = params["region_slug"]
    regions = configured_regions(cfg)
    if slug in regions:
        return regions[slug]
    if repo is not None:
        definition = repo.get_region(slug)
        if definition is not None:
            return region_from_dict(definition)
    raise KeyError(f"unknown region {slug!r}; configured: {sorted(regions)}")


@lru_cache(maxsize=2)
def _geoid(uri: str | None, cache_dir: str) -> GeoidGrid:
    cfg = load_config()
    if uri is None:
        return load_geoid(cfg)
    local = storage.fetch_to_cache(uri, Path(cache_dir))
    return load_geoid_file(local, cfg.egg2015.grid_crs)


def get_geoid(settings: Settings) -> GeoidGrid:
    return _geoid(settings.egg2015_uri, str(settings.cache_dir))


def get_dem_sources(settings: Settings, layout: storage.Layout,
                    refs: list[str]) -> dict[str, dem.TileSource]:
    """Tile sources for the requested reference DEMs, cached under reference/<dem>/."""
    return {ref: dem.SOURCES[ref](settings.cache_dir, s3_prefix=layout.reference_prefix(ref))
            for ref in refs}


def _fetch_with_retry(cfg: Config, region: Region, batch: list[str], retries: int, *,
                      product: products.Product, options: dict):
    for attempt in range(1, retries + 1):
        try:
            return pipeline.fetch_batch(cfg, region, batch, product=product, options=options)
        except Exception:  # noqa: BLE001 - SlideRule/network errors are opaque
            if attempt == retries:
                raise
            wait = 2 ** attempt
            log.warning("SlideRule batch failed (attempt %d/%d), retrying in %ds",
                        attempt, retries, wait, exc_info=True)
            time.sleep(wait)
    return None


def _date(v) -> dt.date | None:
    return dt.date.fromisoformat(v) if isinstance(v, str) else v


def run_job(job_id: str, *, settings: Settings | None = None,
            repo: Repository | None = None) -> dict[str, Any]:
    """Run one queued job to completion. Safe to re-run: every write is an upsert."""
    settings = settings or get_settings()
    repo = repo or Repository(settings.database_url)
    job = repo.get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    params = job["params"]
    cfg = load_config()
    stats: dict[str, Any] = {}
    stage = "discover"
    try:
        repo.update_job(job_id, status="running", stage=stage)
        product = products.get(params.get("product") or "ATL13")
        region = resolve_region(cfg, params, repo)
        layout = storage.Layout(settings, region.slug, product.version, product.name)
        compare = list(params.get("compare") or [])
        dem_opts = params.get("dem") or None

        # 1. discover ------------------------------------------------------
        seeded = product.name == "ATL13" and bool(region.seed_granules())
        include_cmr = params.get("include_cmr")
        if include_cmr is None:   # no curated list -> CMR is the only source
            include_cmr = not seeded
        candidates = pipeline.candidate_granules(
            cfg, region, _date(params.get("start")), _date(params.get("end")),
            include_cmr=bool(include_cmr), product=product,
        )
        done = repo.done_granules(region.slug, product.name)
        todo = [g for g in candidates if g not in done]
        stats.update(product=product.name, candidates=len(candidates),
                     already_loaded=len(candidates) - len(todo))
        if params.get("limit"):
            todo = todo[: int(params["limit"])]
        stats["to_fetch"] = len(todo)
        storage.write_text(layout.manifest(job_id), "granule\n" + "\n".join(todo) + "\n")
        repo.set_granules(region.slug, todo, "pending", job_id=job_id)
        repo.update_job(job_id, stats=stats)
        if not todo:
            repo.update_job(job_id, status="done", stage="load", stats=stats)
            return stats

        # 2. acquire -------------------------------------------------------
        stage = "acquire"
        repo.update_job(job_id, stage=stage)
        batch_size = int(params.get("batch_size") or product.default_batch)
        gmap = pipeline.granule_lookup(todo)
        raw_rows = 0
        for b, i in enumerate(range(0, len(todo), batch_size)):
            batch = todo[i: i + batch_size]
            gdf = _fetch_with_retry(cfg, region, batch, settings.fetch_retries,
                                    product=product, options=params)
            n = 0 if gdf is None else len(gdf)
            log.info("job %s batch %d: %d granules -> %d rows", job_id, b, len(batch), n)
            if n == 0:
                repo.set_granules(region.slug, batch, "empty", job_id=job_id)
                continue
            raw = atl13.raw_frame(gdf).assign(_batch=b)
            uri = layout.raw_batch(job_id, b)
            raw.to_parquet(uri, index=False)
            raw_rows += n
            # Granules of the batch that SlideRule returned nothing for are "empty".
            hit = {gmap.get((int(r), int(c)))
                   for r, c in raw[["rgt", "cycle"]].drop_duplicates().itertuples(index=False)}
            repo.set_granules(region.slug, [g for g in batch if g in hit], "fetched",
                              job_id=job_id, s3_raw_uri=uri)
            repo.set_granules(region.slug, [g for g in batch if g not in hit], "empty",
                              job_id=job_id)
        stats["raw_rows"] = raw_rows
        repo.update_job(job_id, stats=stats)

        # 3. process -------------------------------------------------------
        stage = "process"
        repo.update_job(job_id, stage=stage)
        raw_all = storage.read_concat(storage.list_parquet(layout.raw_dir(job_id)))
        if raw_all.empty:
            repo.update_job(job_id, status="done", stage="load", stats=stats)
            return stats
        seg = pipeline.segments_from_raw(raw_all, todo, product=product)
        geoid = get_geoid(settings) if region.vertical == EGG2015 else None
        pts = pipeline.to_heights(seg, cfg, region, product=product, geoid=geoid)
        if compare:
            pts = dem.add_reference_dems(pts, compare,
                                         sources=get_dem_sources(settings, layout, compare))
        pts.to_parquet(layout.points(job_id), index=False)
        stats["points"] = len(pts)

        passes = None
        if product.name == "ATL13":
            passes = pipeline.pass_levels(pts, cfg, region)
            passes.to_parquet(layout.pass_levels(job_id), index=False)
            stats.update(water_segments=int(pts["water_mask_pass"].sum()),
                         pass_levels=len(passes))
            if "qc_pass" in passes:
                stats["pass_levels_qc"] = int(passes["qc_pass"].fillna(False).sum())

        mask = pipeline.dem_mask(pts, product)
        comparisons = {ref: dem.compare(pts, f"{ref}_m", mask=mask) for ref in compare}
        if comparisons:
            stats["dem_comparison"] = comparisons

        rasters = []
        if dem_opts:
            res = float(dem_opts.get("resolution_m") or 100)
            variables = dem_opts.get("variables") or list(product.dem_variables)
            for var in variables:
                if var not in product.dem_variables:
                    raise ValueError(f"{product.name} has no raster variable {var!r}; "
                                     f"available: {sorted(product.dem_variables)}")
                col, desc = product.dem_variables[var]
                grid = dem.grid_points(pts[mask], col, res)
                with tempfile.TemporaryDirectory() as tmp:
                    local = dem.write_cog(grid, Path(tmp) / f"{var}.tif", description=desc)
                    uri = layout.raster(job_id, var, res)
                    storage.put_file(local, uri)
                rasters.append((var, desc, res, grid, uri))
            stats["rasters"] = [{"variable": v, "resolution_m": r, "uri": u,
                                 **dem.raster_stats(g)} for v, _, r, g, u in rasters]
        repo.update_job(job_id, stats=stats)

        # 4. load ----------------------------------------------------------
        stage = "load"
        repo.update_job(job_id, stage=stage)
        if product.points_in_db:
            repo.load_points(product.name, region.slug, job_id, pts)
        if passes is not None:
            repo.load_pass_levels(region.slug, job_id, passes)
        for ref, st in comparisons.items():
            repo.set_dem_comparison(job_id=job_id, region=region.slug, product=product.name,
                                    dem=ref, height="H_egm2008_m", stats=st)
        for var, desc, res, grid, uri in rasters:
            ring = grid["footprint_4326"] + [grid["footprint_4326"][0]]
            wkt = "POLYGON((" + ", ".join(f"{x} {y}" for x, y in ring) + "))"
            repo.add_raster(job_id=job_id, region=region.slug, product=product.name,
                            variable=var, description=desc, resolution_m=res,
                            crs=grid["crs"],
                            vertical_datum=None if var == "chm" else region.vertical_datum,
                            s3_uri=uri, stats=dem.raster_stats(grid), footprint_wkt=wkt)
        per_granule = pts.groupby("granule").size().to_dict() if "granule" in pts else {}
        fetched = [g["granule"] for g in repo.list_granules(region.slug, "fetched",
                                                            product.name)
                   if str(g["job_id"]) == job_id]
        repo.set_granules(region.slug, fetched, "loaded", job_id=job_id,
                          n_rows={k: int(v) for k, v in per_granule.items()})
        repo.update_job(job_id, status="done", stats=stats)
        return stats
    except Exception as exc:
        log.exception("job %s failed in %s", job_id, stage)
        repo.update_job(job_id, status="failed", stage=stage, stats=stats,
                        error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}")
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", required=True, help="configured or registered region slug")
    ap.add_argument("--product", default="ATL13", choices=sorted(products.PRODUCTS))
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--cmr", action="store_true", default=None,
                    help="merge a live CMR search (default: only when no seed list)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=None)
    ap.add_argument("--compare", nargs="*", default=[], choices=dem.REFERENCE_DEMS)
    ap.add_argument("--dem-res", type=float, default=None,
                    help="grid the product's raster variables at this resolution (m)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    repo = Repository(settings.database_url)
    params = {"region_slug": args.region, "product": args.product, "start": args.start,
              "end": args.end, "include_cmr": args.cmr, "limit": args.limit,
              "batch_size": args.batch_size, "compare": args.compare,
              "dem": {"resolution_m": args.dem_res} if args.dem_res else None}
    job_id = repo.create_job(args.region, params, args.product)
    print(f"job {job_id}")
    stats = run_job(job_id, settings=settings, repo=repo)
    print(pd.Series(stats).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
