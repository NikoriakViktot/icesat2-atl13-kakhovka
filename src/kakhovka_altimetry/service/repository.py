"""PostGIS access for the service: jobs, granule bookkeeping and the bulk loads.

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

# segments parquet column -> icesat2.segments column
SEGMENT_COLUMNS = {
    "time": "time",
    "beam": "beam",
    "granule": "granule",
    "rgt": "rgt",
    "cycle": "cycle",
    "segment_id": "segment_id",
    "lat": "lat",
    "lon": "lon",
    "h_wgs84_m": "h_wgs84_m",
    "H_egm2008_m": "h_egm2008_m",
    "stdev_water_surf_m": "stdev_water_surf_m",
    "water_depth_m": "water_depth_m",
    "zeta_egg2015_m": "zeta_egg2015_m",
    "H_evrs_egg2015_m": "h_evrs_egg2015_m",
    "egm2008_minus_evrs_m": "egm2008_minus_evrs_m",
    "period": "period",
    "water_mask_pass": "water_mask_pass",
}

PASS_LEVEL_DB_COLUMNS = [
    "date", "rgt", "beam", "datetime", "year", "transect", "period", "n_points",
    "median_wse_evrs_m", "mean_wse_evrs_m", "std_m", "mad_m", "nmad_m",
    "p05_m", "p95_m", "range_m", "along_track_slope_m_per_km", "track_length_km",
    "mean_stdev_water_surf_m", "lat_mean", "lon_mean", "qc_pass", "qc_flags",
]

DONE_STATUSES = ("loaded", "empty")


class Repository:
    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def conn(self):
        with psycopg.connect(self.dsn, row_factory=dict_row) as c:
            yield c

    # ------------------------------------------------------------------ jobs
    def create_job(self, region: str, params: dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        with self.conn() as c:
            c.execute(
                "INSERT INTO icesat2.jobs (job_id, region, params) VALUES (%s, %s, %s)",
                (job_id, region, json.dumps(params)),
            )
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM icesat2.jobs WHERE job_id = %s", (job_id,)
            ).fetchone()

    def list_jobs(self, region: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM icesat2.jobs"
        args: list[Any] = []
        if region:
            sql += " WHERE region = %s"
            args.append(region)
        sql += " ORDER BY created_at DESC LIMIT %s"
        args.append(limit)
        with self.conn() as c:
            return c.execute(sql, args).fetchall()

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
            args.append(json.dumps(stats))
        if error is not None:
            sets.append("error = %s")
            args.append(error)
        if not sets:
            return
        with self.conn() as c:
            c.execute(f"UPDATE icesat2.jobs SET {', '.join(sets)} WHERE job_id = %s",
                      [*args, job_id])

    # -------------------------------------------------------------- granules
    def done_granules(self, region: str) -> set[str]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT granule FROM icesat2.granules WHERE region = %s AND status = ANY(%s)",
                (region, list(DONE_STATUSES)),
            ).fetchall()
        return {r["granule"] for r in rows}

    def set_granules(self, region: str, granules: Iterable[str], status: str, *,
                     job_id: str, s3_raw_uri: str | None = None,
                     n_rows: dict[str, int] | None = None) -> None:
        rows = []
        for g in granules:
            info = GranuleInfo.parse(g)
            rows.append((region, g, info.rgt, info.cycle, info.acquisition_time,
                         f"{info.release}_{info.version}", status,
                         (n_rows or {}).get(g), s3_raw_uri, job_id))
        if not rows:
            return
        with self.conn() as c, c.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO icesat2.granules
                    (region, granule, rgt, cycle, acq_time, version, status, n_rows,
                     s3_raw_uri, job_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (region, granule) DO UPDATE SET
                    status = EXCLUDED.status,
                    n_rows = coalesce(EXCLUDED.n_rows, icesat2.granules.n_rows),
                    s3_raw_uri = coalesce(EXCLUDED.s3_raw_uri, icesat2.granules.s3_raw_uri),
                    job_id = EXCLUDED.job_id,
                    updated_at = now()
                """,
                rows,
            )

    def list_granules(self, region: str | None = None, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM icesat2.granules WHERE true"
        args: list[Any] = []
        if region:
            sql += " AND region = %s"
            args.append(region)
        if status:
            sql += " AND status = %s"
            args.append(status)
        sql += " ORDER BY acq_time"
        with self.conn() as c:
            return c.execute(sql, args).fetchall()

    # ---------------------------------------------------------------- loads
    def load_segments(self, region: str, job_id: str, evrs: pd.DataFrame) -> int:
        """Upsert EVRS segments; returns the number of rows sent."""
        if evrs.empty:
            return 0
        src = [c for c in SEGMENT_COLUMNS if c in evrs.columns]
        df = evrs[src].rename(columns=SEGMENT_COLUMNS)
        cols = list(df.columns)
        update = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols
                           if c not in ("time", "beam")) + ", job_id = EXCLUDED.job_id, " \
                                                           "geom = EXCLUDED.geom"
        with self.conn() as c:
            c.execute(f"""
                CREATE TEMP TABLE stage_segments ON COMMIT DROP AS
                SELECT {', '.join(cols)} FROM icesat2.segments WITH NO DATA""")
            _copy_csv(c, "stage_segments", df)
            c.execute(f"""
                INSERT INTO icesat2.segments (region, {', '.join(cols)}, job_id, geom)
                SELECT %s, {', '.join(cols)}, %s,
                       ST_SetSRID(ST_MakePoint(lon, lat), 4326)
                FROM stage_segments
                ON CONFLICT (region, beam, time) DO UPDATE SET {update}""",
                      (region, job_id))
        return len(df)

    def load_pass_levels(self, region: str, job_id: str, passes: pd.DataFrame) -> int:
        """Upsert pass levels and draw each pass as a line through its water segments."""
        if passes.empty:
            return 0
        df = passes.reindex(columns=PASS_LEVEL_DB_COLUMNS)
        cols = list(df.columns)
        update = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols
                           if c not in ("date", "rgt", "beam")) + ", job_id = EXCLUDED.job_id"
        with self.conn() as c:
            c.execute(f"""
                CREATE TEMP TABLE stage_passes ON COMMIT DROP AS
                SELECT {', '.join(cols)} FROM icesat2.pass_levels WITH NO DATA""")
            _copy_csv(c, "stage_passes", df)
            c.execute(f"""
                INSERT INTO icesat2.pass_levels (region, {', '.join(cols)}, job_id)
                SELECT %s, {', '.join(cols)}, %s FROM stage_passes
                ON CONFLICT (region, date, rgt, beam) DO UPDATE SET {update}""",
                      (region, job_id))
            c.execute("""
                UPDATE icesat2.pass_levels p SET geom = s.line
                FROM (
                    SELECT (time AT TIME ZONE 'UTC')::date AS d, rgt, beam,
                           ST_MakeLine(geom ORDER BY time) AS line
                    FROM icesat2.segments
                    WHERE region = %s AND job_id = %s AND water_mask_pass
                    GROUP BY 1, 2, 3
                    HAVING count(*) > 1
                ) s
                WHERE p.region = %s AND p.date = s.d AND p.rgt = s.rgt AND p.beam = s.beam""",
                      (region, job_id, region))
        return len(df)

    # --------------------------------------------------------------- reads
    def pass_levels_geojson(self, region: str, *, start=None, end=None,
                            qc_pass: bool | None = None) -> dict:
        where, args = _pass_filter(region, start, end, qc_pass)
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
                FROM icesat2.pass_levels p WHERE {where}""", args).fetchone()
        return row["fc"]

    def pass_levels_frame(self, region: str, *, start=None, end=None,
                          qc_pass: bool | None = None) -> pd.DataFrame:
        where, args = _pass_filter(region, start, end, qc_pass)
        with self.conn() as c:
            rows = c.execute(
                f"SELECT {', '.join(PASS_LEVEL_DB_COLUMNS)} FROM icesat2.pass_levels "
                f"WHERE {where} ORDER BY datetime", args).fetchall()
        return pd.DataFrame(rows, columns=PASS_LEVEL_DB_COLUMNS)

    def counts(self, region: str) -> dict[str, int]:
        with self.conn() as c:
            seg = c.execute("SELECT count(*) n FROM icesat2.segments WHERE region = %s",
                            (region,)).fetchone()["n"]
            pas = c.execute("SELECT count(*) n FROM icesat2.pass_levels WHERE region = %s",
                            (region,)).fetchone()["n"]
        return {"segments": int(seg), "pass_levels": int(pas)}

    def known_regions(self) -> list[str]:
        with self.conn() as c:
            rows = c.execute("SELECT DISTINCT region FROM icesat2.jobs ORDER BY 1").fetchall()
        return [r["region"] for r in rows]


def _pass_filter(region, start, end, qc_pass):
    where, args = ["region = %s"], [region]
    if start is not None:
        where.append("date >= %s")
        args.append(start)
    if end is not None:
        where.append("date <= %s")
        args.append(end)
    if qc_pass is not None:
        where.append("qc_pass = %s")
        args.append(qc_pass)
    return " AND ".join(where), args


def _copy_csv(conn, table: str, df: pd.DataFrame) -> None:
    """COPY ``df`` into ``table`` (columns in frame order); NaN/None -> NULL."""
    buf = io.StringIO()
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = pd.to_datetime(out[col], utc=True).dt.strftime("%Y-%m-%d %H:%M:%S.%f+00")
    out.to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    with conn.cursor().copy(
        f"COPY {table} ({', '.join(df.columns)}) FROM STDIN WITH (FORMAT csv)"
    ) as cp:
        while chunk := buf.read(1 << 20):
            cp.write(chunk)
