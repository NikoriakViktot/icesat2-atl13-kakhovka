"""The job runner: discover -> acquire -> process -> load.

    python -m kakhovka_altimetry.service.worker --region kakhovka [--start D] [--end D]
        [--cmr] [--limit N]                     # create + run one job synchronously
    rq worker icesat2                           # consume jobs queued by the API

Every stage records itself in ``icesat2.jobs``. Granules already ``loaded``/``empty``
for the region are skipped at discovery, so a repeated job only pulls new passes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import time
import traceback
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .. import atl13, pipeline
from ..config import Config, load_config
from ..regions import Region, configured_regions, region_from_dict
from ..vertical import GeoidGrid, load_geoid, load_geoid_file
from . import storage
from .repository import Repository
from .settings import Settings, get_settings

log = logging.getLogger("kakhovka_altimetry.service")


def resolve_region(cfg: Config, params: dict[str, Any]) -> Region:
    """A configured region by slug, or an inline one from the request."""
    if params.get("region"):
        return region_from_dict(params["region"])
    slug = params["region_slug"]
    regions = configured_regions(cfg)
    if slug not in regions:
        raise KeyError(f"unknown region {slug!r}; configured: {sorted(regions)}")
    return regions[slug]


@lru_cache(maxsize=2)
def _geoid(uri: str | None, cache_dir: str) -> GeoidGrid:
    cfg = load_config()
    if uri is None:
        return load_geoid(cfg)
    local = storage.fetch_to_cache(uri, Path(cache_dir))
    return load_geoid_file(local, cfg.egg2015.grid_crs)


def get_geoid(settings: Settings) -> GeoidGrid:
    return _geoid(settings.egg2015_uri, str(settings.cache_dir))


def _fetch_with_retry(cfg: Config, region: Region, batch: list[str], retries: int):
    for attempt in range(1, retries + 1):
        try:
            return pipeline.fetch_batch(cfg, region, batch)
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
        region = resolve_region(cfg, params)
        layout = storage.Layout(settings, region.slug, cfg.product.version)

        # 1. discover ------------------------------------------------------
        candidates = pipeline.candidate_granules(
            cfg, region, _date(params.get("start")), _date(params.get("end")),
            include_cmr=bool(params.get("include_cmr")),
        )
        done = repo.done_granules(region.slug)
        todo = [g for g in candidates if g not in done]
        stats.update(candidates=len(candidates), already_loaded=len(candidates) - len(todo))
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
        batch_size = int(params.get("batch_size") or settings.batch_size)
        gmap = pipeline.granule_lookup(todo)
        raw_rows = 0
        for b, i in enumerate(range(0, len(todo), batch_size)):
            batch = todo[i: i + batch_size]
            gdf = _fetch_with_retry(cfg, region, batch, settings.fetch_retries)
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
        segments = pipeline.segments_from_raw(raw_all, todo)
        evrs = pipeline.to_evrs(segments, cfg, region, geoid=get_geoid(settings))
        passes = pipeline.pass_levels(evrs, cfg, region)
        evrs.to_parquet(layout.segments(job_id), index=False)
        passes.to_parquet(layout.pass_levels(job_id), index=False)
        stats.update(segments=len(evrs), water_segments=int(evrs["water_mask_pass"].sum()),
                     pass_levels=len(passes))
        if "qc_pass" in passes:
            stats["pass_levels_qc"] = int(passes["qc_pass"].fillna(False).sum())
        repo.update_job(job_id, stats=stats)

        # 4. load ----------------------------------------------------------
        stage = "load"
        repo.update_job(job_id, stage=stage)
        repo.load_segments(region.slug, job_id, evrs)
        repo.load_pass_levels(region.slug, job_id, passes)
        per_granule = evrs.groupby("granule").size().to_dict() if "granule" in evrs else {}
        fetched = [g["granule"] for g in repo.list_granules(region.slug, "fetched")
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
    ap.add_argument("--region", required=True, help="configured region slug")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--cmr", action="store_true", help="merge a live CMR search")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    repo = Repository(settings.database_url)
    params = {"region_slug": args.region, "start": args.start, "end": args.end,
              "include_cmr": args.cmr, "limit": args.limit, "batch_size": args.batch_size}
    job_id = repo.create_job(args.region, params)
    print(f"job {job_id}")
    stats = run_job(job_id, settings=settings, repo=repo)
    print(pd.Series(stats).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
