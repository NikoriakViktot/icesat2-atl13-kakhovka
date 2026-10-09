"""PostGIS access for the service: jobs, regions, granule bookkeeping, bulk loads,
rasters and DEM comparisons.

Bulk loads go ``COPY`` -> temporary staging table -> ``INSERT ... ON CONFLICT DO
UPDATE``, so re-running a job (or re-loading the same S3 run) never duplicates rows.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from ..discovery import GranuleInfo

# frame column -> icesat2.atl13_segments column
ATL13_SEGMENT_COLUMNS = {
    "time": "time", "beam": "beam", "granule": "granule", "rgt": "rgt", "cycle": "cycle",
    "segment_id": "segment_id", "lat": "lat", "lon": "lon",
    "h_wgs84_m": "h_wgs84_m", "H_egm2008_m": "h_egm2008_m",
    "stdev_water_surf_m": "stdev_water_surf_m", "water_depth_m": "water_depth_m",
    "zeta_egg2015_m": "zeta_egg2015_m", "H_evrs_egg2015_m": "h_evrs_egg2015_m",
    "egm2008_minus_evrs_m": "egm2008_minus_evrs_m",
    "N_m": "n_m", "H_m": "wse_m", "vertical_datum": "vertical_datum",
    "cop30_m": "cop30_m", "fabdem_m": "fabdem_m",
    "period": "period", "water_mask_pass": "water_mask_pass",
}

# frame column -> icesat2.atl08_segments column
ATL08_SEGMENT_COLUMNS = {
    "time": "time", "beam": "beam", "granule": "granule", "rgt": "rgt", "cycle": "cycle",
    "segment_id": "segment_id", "lat": "lat", "lon": "lon",
    "h_te_median_m": "h_te_median_m", "h_te_uncertainty_m": "h_te_uncertainty_m",
    "terrain_slope": "terrain_slope", "h_canopy_m": "h_canopy_m",
    "h_mean_canopy_m": "h_mean_canopy_m", "h_max_canopy_m": "h_max_canopy_m",
    "h_canopy_uncertainty_m": "h_canopy_uncertainty_m", "canopy_openness": "canopy_openness",
    "n_te_photons": "n_te_photons", "n_ca_photons": "n_ca_photons",
    "segment_landcover": "segment_landcover", "segment_snowcover": "segment_snowcover",
    "solar_elevation": "solar_elevation",
    "N_m": "n_m", "H_m": "h_m", "H_egm2008_m": "h_egm2008_m",
    "vertical_datum": "vertical_datum", "cop30_m": "cop30_m", "fabdem_m": "fabdem_m",
    "period": "period",
}

POINT_TABLES = {
    "ATL13": ("icesat2.atl13_segments", ATL13_SEGMENT_COLUMNS),
    "ATL08": ("icesat2.atl08_segments", ATL08_SEGMENT_COLUMNS),
}

PASS_LEVEL_DB_COLUMNS = [
    "date", "rgt", "beam", "datetime", "year", "transect", "period", "n_points",
    "median_wse_m", "mean_wse_m", "std_m", "mad_m", "nmad_m",
    "p05_m", "p95_m", "range_m", "along_track_slope_m_per_km", "track_length_km",
    "mean_stdev_water_surf_m", "lat_mean", "lon_mean", "qc_pass", "qc_flags",
    "vertical_datum",
]

DEM_STAT_COLUMNS = ["n", "median_m", "nmad_m", "mean_m", "std_m", "rmse_m", "p05_m", "p95_m"]

DONE_STATUSES = ("loaded", "empty")


class Repository:
    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def conn(self):
        with psycopg.connect(self.dsn, row_factory=dict_row) as c:
            yield c

    # ------------------------------------------------------------------ jobs
    def create_job(self, region: str, params: dict[str, Any], product: str = "ATL13", *,
                   client: str | None = None, requested_by: str | None = None) -> str:
        job_id = str(uuid.uuid4())
        with self.conn() as c:
            c.execute(
                "INSERT INTO icesat2.jobs (job_id, region, product, params, client, requested_by) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (job_id, region, product, json.dumps(params), client, requested_by),
            )
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM icesat2.jobs WHERE job_id = %s", (job_id,)
            ).fetchone()

    def list_jobs(self, region: str | None = None, product: str | None = None,
                  limit: int = 50, *, client: str | None = None,
                  requested_by: str | None = None) -> list[dict]:
        where, args = ["true"], []
        for col, val in (("region", region), ("product", product), ("client", client),
                         ("requested_by", requested_by)):
            if val:
                where.append(f"{col} = %s")
                args.append(val)
        args.append(limit)
        with self.conn() as c:
            return c.execute(
                f"SELECT * FROM icesat2.jobs WHERE {' AND '.join(where)} "
                f"ORDER BY created_at DESC LIMIT %s", args).fetchall()

    def update_job(self, job_id: str, *, status: str | None = None, stage: str | None = None,
                   stats: dict | None = None, error: str | None = None) -> None:
        sets, args = [], []
        if status is not None:
            sets.append("status = %s")
            args.append(status)
            if status == "running":
                sets.append("started_at = coalesce(started_at, now())")
            if status in ("done", "failed"):
                sets.append("finished_at = now()")
        if stage is not None:
            sets.append("stage = %s")
            args.append(stage)
        if stats is not None:
            sets.append("stats = stats || %s::jsonb")
            args.append(json.dumps(stats, default=_json_default))
        if error is not None:
            sets.append("error = %s")
            args.append(error)
        if not sets:
            return
        with self.conn() as c:
            c.execute(f"UPDATE icesat2.jobs SET {', '.join(sets)} WHERE job_id = %s",
                      [*args, job_id])

    # --------------------------------------------------------------- regions
    def upsert_region(self, definition: dict[str, Any], footprint_wkt: str, *,
                      client: str | None = None, requested_by: str | None = None) -> bool:
        """Insert or update; returns False (nothing written) when the slug belongs to
        another owner (a different client, or a different end user of the same client)."""
        with self.conn() as c:
            row = c.execute(
                """
                INSERT INTO icesat2.regions (slug, definition, footprint, client, requested_by)
                VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s, %s)
                ON CONFLICT (slug) DO UPDATE SET
                    definition = EXCLUDED.definition, footprint = EXCLUDED.footprint,
                    updated_at = now()
                WHERE icesat2.regions.client IS NOT DISTINCT FROM EXCLUDED.client
                  AND icesat2.regions.requested_by IS NOT DISTINCT FROM EXCLUDED.requested_by
                RETURNING slug
                """,
                (definition["slug"], json.dumps(definition), footprint_wkt, client,
                 requested_by),
            ).fetchone()
        return row is not None

    def get_region(self, slug: str) -> dict | None:
        row = self.get_region_row(slug)
        return row["definition"] if row else None

    def get_region_row(self, slug: str) -> dict | None:
        with self.conn() as c:
            return c.execute("SELECT definition, client, requested_by, created_at, updated_at "
                             "FROM icesat2.regions WHERE slug = %s", (slug,)).fetchone()

    def list_regions(self, *, client: str | None = None,
                     requested_by: str | None = None) -> list[dict]:
        where, args = ["true"], []
        for col, val in (("client", client), ("requested_by", requested_by)):
            if val:
                where.append(f"{col} = %s")
                args.append(val)
        with self.conn() as c:
            rows = c.execute(
                f"SELECT definition, client, requested_by FROM icesat2.regions "
                f"WHERE {' AND '.join(where)} ORDER BY slug", args).fetchall()
        return [{**r["definition"], "client": r["client"], "requested_by": r["requested_by"]}
                for r in rows]

    def known_regions(self) -> list[str]:
        with self.conn() as c:
            rows = c.execute("SELECT DISTINCT region FROM icesat2.jobs ORDER BY 1").fetchall()
        return [r["region"] for r in rows]

    # -------------------------------------------------------------- granules
    def done_granules(self, region: str, product: str = "ATL13") -> set[str]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT granule FROM icesat2.granules "
                "WHERE region = %s AND product = %s AND status = ANY(%s)",
                (region, product, list(DONE_STATUSES)),
            ).fetchall()
        return {r["granule"] for r in rows}

    def set_granules(self, region: str, granules: Iterable[str], status: str, *,
                     job_id: str, s3_raw_uri: str | None = None,
                     n_rows: dict[str, int] | None = None) -> None:
        rows = []
        for g in granules:
            info = GranuleInfo.parse(g)
            rows.append((region, info.product, g, info.rgt, info.cycle, info.acquisition_time,
                         f"{info.release}_{info.version}", status,
                         (n_rows or {}).get(g), s3_raw_uri, job_id))
        if not rows:
            return
        with self.conn() as c, c.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO icesat2.granules
                    (region, product, granule, rgt, cycle, acq_time, version, status,
                     n_rows, s3_raw_uri, job_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (region, product, granule) DO UPDATE SET
                    status = EXCLUDED.status,
                    n_rows = coalesce(EXCLUDED.n_rows, icesat2.granules.n_rows),
                    s3_raw_uri = coalesce(EXCLUDED.s3_raw_uri, icesat2.granules.s3_raw_uri),
                    job_id = EXCLUDED.job_id,
                    updated_at = now()
                """,
                rows,
            )

    def list_granules(self, region: str | None = None, status: str | None = None,
                      product: str | None = None) -> list[dict]:
        sql = "SELECT * FROM icesat2.granules WHERE true"
        args: list[Any] = []
        for col, val in (("region", region), ("status", status), ("product", product)):
            if val:
                sql += f" AND {col} = %s"
                args.append(val)
        sql += " ORDER BY acq_time"
        with self.conn() as c:
            return c.execute(sql, args).fetchall()

    # ---------------------------------------------------------------- loads
    def load_points(self, product: str, region: str, job_id: str, df: pd.DataFrame) -> int:
        """Upsert ATL13 / ATL08 points; returns the number of rows sent."""
        if df.empty:
            return 0
        table, mapping = POINT_TABLES[product]
        src = [c for c in mapping if c in df.columns]
        frame = df[src].rename(columns=mapping)
        cols = list(frame.columns)
        update = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("time", "beam"))
        with self.conn() as c:
            c.execute(f"CREATE TEMP TABLE stage ON COMMIT DROP AS "
                      f"SELECT {', '.join(cols)} FROM {table} WITH NO DATA")
            _copy_csv(c, "stage", frame)
            c.execute(f"""
                INSERT INTO {table} (region, {', '.join(cols)}, job_id, geom)
                SELECT %s, {', '.join(cols)}, %s, ST_SetSRID(ST_MakePoint(lon, lat), 4326)
                FROM stage
                ON CONFLICT (region, beam, time) DO UPDATE SET {update},
                    job_id = EXCLUDED.job_id, geom = EXCLUDED.geom""",
                      (region, job_id))
        return len(frame)

    def load_segments(self, region: str, job_id: str, evrs: pd.DataFrame) -> int:
        return self.load_points("ATL13", region, job_id, evrs)

    def load_pass_levels(self, region: str, job_id: str, passes: pd.DataFrame) -> int:
        """Upsert ATL13 pass levels and draw each pass through its water segments."""
        if passes.empty:
            return 0
        df = passes.reindex(columns=PASS_LEVEL_DB_COLUMNS)
        cols = list(df.columns)
        update = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols
                           if c not in ("date", "rgt", "beam")) + ", job_id = EXCLUDED.job_id"
        with self.conn() as c:
            c.execute(f"CREATE TEMP TABLE stage_passes ON COMMIT DROP AS "
                      f"SELECT {', '.join(cols)} FROM icesat2.atl13_pass_levels WITH NO DATA")
            _copy_csv(c, "stage_passes", df)
            c.execute(f"""
                INSERT INTO icesat2.atl13_pass_levels (region, {', '.join(cols)}, job_id)
                SELECT %s, {', '.join(cols)}, %s FROM stage_passes
                ON CONFLICT (region, date, rgt, beam) DO UPDATE SET {update}""",
                      (region, job_id))
            c.execute("""
                UPDATE icesat2.atl13_pass_levels p SET geom = s.line
                FROM (
                    SELECT (time AT TIME ZONE 'UTC')::date AS d, rgt, beam,
                           ST_MakeLine(geom ORDER BY time) AS line
                    FROM icesat2.atl13_segments
                    WHERE region = %s AND job_id = %s AND water_mask_pass
                    GROUP BY 1, 2, 3
                    HAVING count(*) > 1
                ) s
                WHERE p.region = %s AND p.date = s.d AND p.rgt = s.rgt AND p.beam = s.beam""",
                      (region, job_id, region))
        return len(df)

    # ------------------------------------------------------ rasters / DEM stats
    def add_raster(self, *, job_id: str, region: str, product: str, variable: str,
                   description: str, resolution_m: float, crs: str, vertical_datum: str | None,
                   s3_uri: str, stats: dict, footprint_wkt: str) -> str:
        raster_id = str(uuid.uuid4())
        with self.conn() as c:
            c.execute("DELETE FROM icesat2.rasters WHERE job_id = %s AND variable = %s "
                      "AND resolution_m = %s", (job_id, variable, resolution_m))
            c.execute(
                """
                INSERT INTO icesat2.rasters
                    (raster_id, job_id, region, product, variable, description, resolution_m,
                     crs, vertical_datum, s3_uri, stats, footprint)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        ST_GeomFromText(%s, 4326))
                """,
                (raster_id, job_id, region, product, variable, description, resolution_m,
                 crs, vertical_datum, s3_uri, json.dumps(stats, default=_json_default),
                 footprint_wkt),
            )
        return raster_id

    def list_rasters(self, *, region: str | None = None, product: str | None = None,
                     variable: str | None = None, job_id: str | None = None) -> list[dict]:
        sql = ("SELECT raster_id, job_id, region, product, variable, description, "
               "resolution_m, crs, vertical_datum, s3_uri, stats, created_at, "
               "ST_AsGeoJSON(footprint)::json AS footprint FROM icesat2.rasters WHERE true")
        args: list[Any] = []
        for col, val in (("region", region), ("product", product), ("variable", variable),
                         ("job_id", job_id)):
            if val:
                sql += f" AND {col} = %s"
                args.append(val)
        sql += " ORDER BY created_at DESC"
        with self.conn() as c:
            return c.execute(sql, args).fetchall()

    def get_raster(self, raster_id: str) -> dict | None:
        with self.conn() as c:
            return c.execute(
                "SELECT raster_id, job_id, region, product, variable, description, "
                "resolution_m, crs, vertical_datum, s3_uri, stats, created_at, "
                "ST_AsGeoJSON(footprint)::json AS footprint FROM icesat2.rasters "
                "WHERE raster_id = %s", (raster_id,)).fetchone()

    def set_dem_comparison(self, *, job_id: str, region: str, product: str, dem: str,
                           height: str, stats: dict) -> None:
        vals = [stats.get(k) for k in DEM_STAT_COLUMNS]
        with self.conn() as c:
            c.execute(
                f"""
                INSERT INTO icesat2.dem_comparisons
                    (job_id, region, product, dem, height, {', '.join(DEM_STAT_COLUMNS)})
                VALUES (%s, %s, %s, %s, %s, {', '.join(['%s'] * len(DEM_STAT_COLUMNS))})
                ON CONFLICT (job_id, dem) DO UPDATE SET
                    {', '.join(f'{k} = EXCLUDED.{k}' for k in DEM_STAT_COLUMNS)},
                    height = EXCLUDED.height
                """,
                (job_id, region, product, dem, height, *vals),
            )

    def dem_comparisons(self, *, job_id: str | None = None, region: str | None = None
                        ) -> list[dict]:
        sql = "SELECT * FROM icesat2.dem_comparisons WHERE true"
        args: list[Any] = []
        if job_id:
            sql += " AND job_id = %s"
            args.append(job_id)
        if region:
            sql += " AND region = %s"
            args.append(region)
        with self.conn() as c:
            return c.execute(sql + " ORDER BY created_at DESC", args).fetchall()

    # --------------------------------------------------------------- reads
    def pass_levels_geojson(self, region: str, *, start=None, end=None,
                            qc_pass: bool | None = None) -> dict:
        where, args = _filter(region, start, end, "date", qc_pass=qc_pass)
        with self.conn() as c:
            row = c.execute(f"""
                SELECT json_build_object(
                    'type', 'FeatureCollection',
                    'features', coalesce(json_agg(json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(coalesce(
                            geom, ST_SetSRID(ST_MakePoint(lon_mean, lat_mean), 4326)))::json,
                        'properties', to_jsonb(p) - 'geom' - 'job_id'
                    ) ORDER BY datetime), '[]'::json)
                ) AS fc
                FROM icesat2.atl13_pass_levels p WHERE {where}""", args).fetchone()
        return row["fc"]

    def pass_levels_frame(self, region: str, *, start=None, end=None,
                          qc_pass: bool | None = None) -> pd.DataFrame:
        where, args = _filter(region, start, end, "date", qc_pass=qc_pass)
        with self.conn() as c:
            rows = c.execute(
                f"SELECT {', '.join(PASS_LEVEL_DB_COLUMNS)} FROM icesat2.atl13_pass_levels "
                f"WHERE {where} ORDER BY datetime", args).fetchall()
        return pd.DataFrame(rows, columns=PASS_LEVEL_DB_COLUMNS)

    def points_frame(self, product: str, region: str, *, start=None, end=None,
                     limit: int = 100_000) -> pd.DataFrame:
        table, mapping = POINT_TABLES[product]
        cols = list(dict.fromkeys(mapping.values()))
        where, args = _filter(region, start, end, "(time AT TIME ZONE 'UTC')::date")
        with self.conn() as c:
            rows = c.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE {where} "
                             f"ORDER BY time LIMIT %s", [*args, limit]).fetchall()
        return pd.DataFrame(rows, columns=cols)

    def counts(self, region: str) -> dict[str, int]:
        out = {}
        with self.conn() as c:
            for name, table in (("atl13_segments", "icesat2.atl13_segments"),
                                ("atl13_pass_levels", "icesat2.atl13_pass_levels"),
                                ("atl08_segments", "icesat2.atl08_segments"),
                                ("rasters", "icesat2.rasters")):
                out[name] = int(c.execute(f"SELECT count(*) n FROM {table} WHERE region = %s",
                                          (region,)).fetchone()["n"])
        return out


def _filter(region, start, end, date_expr, *, qc_pass: bool | None = None):
    where, args = ["region = %s"], [region]
    if start is not None:
        where.append(f"{date_expr} >= %s")
        args.append(start)
    if end is not None:
        where.append(f"{date_expr} <= %s")
        args.append(end)
    if qc_pass is not None:
        where.append("qc_pass = %s")
        args.append(qc_pass)
    return " AND ".join(where), args


def _json_default(o):
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError(type(o))


def _copy_csv(conn, table: str, df: pd.DataFrame) -> None:
    """COPY ``df`` into ``table`` (columns in frame order); NaN/None -> NULL."""
    buf = io.StringIO()
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            out[col] = pd.to_datetime(s, utc=True).dt.strftime("%Y-%m-%d %H:%M:%S.%f+00")
        elif pd.api.types.is_float_dtype(s):
            v = s.dropna()
            # integer-valued floats (ints that met a NaN) must not reach int columns as "12.0"
            if len(v) and (v == v.round()).all() and v.abs().max() < 2**53:
                out[col] = s.astype("Int64")
    out.to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    with conn.cursor().copy(
        f"COPY {table} ({', '.join(df.columns)}) FROM STDIN WITH (FORMAT csv)"
    ) as cp:
        while chunk := buf.read(1 << 20):
            cp.write(chunk)
