"""icesat2 schema: jobs, granules, segments (partitioned by year), pass_levels

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

FIRST_YEAR, LAST_YEAR = 2018, 2035


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE SCHEMA IF NOT EXISTS icesat2")

    op.execute("""
    CREATE TABLE icesat2.jobs (
        job_id       uuid PRIMARY KEY,
        region       text        NOT NULL,
        params       jsonb       NOT NULL,
        status       text        NOT NULL DEFAULT 'queued',  -- queued|running|done|failed
        stage        text,                                   -- discover|acquire|process|load
        stats        jsonb       NOT NULL DEFAULT '{}'::jsonb,
        error        text,
        created_at   timestamptz NOT NULL DEFAULT now(),
        started_at   timestamptz,
        finished_at  timestamptz
    )""")
    op.execute("CREATE INDEX jobs_region_idx ON icesat2.jobs (region, created_at DESC)")

    op.execute("""
    CREATE TABLE icesat2.granules (
        region       text        NOT NULL,
        granule      text        NOT NULL,
        rgt          int         NOT NULL,
        cycle        int         NOT NULL,
        acq_time     timestamptz NOT NULL,
        version      text        NOT NULL,
        status       text        NOT NULL,   -- pending|fetched|empty|loaded|failed
        n_rows       int,
        s3_raw_uri   text,
        job_id       uuid REFERENCES icesat2.jobs (job_id),
        updated_at   timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (region, granule)
    )""")

    # One row per ATL13 water-surface segment. (region, beam, time) is unique in
    # every region pulled so far (granule is NULL for the downstream bodies, whose
    # seed lists are not attributable per segment, so it cannot be part of the key).
    op.execute("""
    CREATE TABLE icesat2.segments (
        region                text             NOT NULL,
        time                  timestamptz      NOT NULL,
        beam                  text             NOT NULL,
        granule               text,
        rgt                   int,
        cycle                 int,
        segment_id            bigint,
        lat                   double precision NOT NULL,
        lon                   double precision NOT NULL,
        h_wgs84_m             double precision,
        h_egm2008_m           double precision,
        stdev_water_surf_m    double precision,
        water_depth_m         double precision,
        zeta_egg2015_m        double precision,
        h_evrs_egg2015_m      double precision,
        egm2008_minus_evrs_m  double precision,
        period                text,
        water_mask_pass       boolean,
        job_id                uuid,
        geom                  geometry(Point, 4326) NOT NULL,
        PRIMARY KEY (region, beam, time)
    ) PARTITION BY RANGE (time)""")
    for y in range(FIRST_YEAR, LAST_YEAR + 1):
        op.execute(f"""
        CREATE TABLE icesat2.segments_{y} PARTITION OF icesat2.segments
            FOR VALUES FROM ('{y}-01-01 00:00+00') TO ('{y + 1}-01-01 00:00+00')""")
    op.execute("CREATE TABLE icesat2.segments_default PARTITION OF icesat2.segments DEFAULT")
    op.execute("CREATE INDEX segments_geom_idx ON icesat2.segments USING gist (geom)")
    op.execute("CREATE INDEX segments_region_time_idx ON icesat2.segments (region, time)")
    op.execute("CREATE INDEX segments_job_idx ON icesat2.segments (job_id)")

    # One level per (date, rgt, beam). qc_* are NULL for river regions (basic stats).
    op.execute("""
    CREATE TABLE icesat2.pass_levels (
        region                      text             NOT NULL,
        date                        date             NOT NULL,
        rgt                         int              NOT NULL,
        beam                        text             NOT NULL,
        datetime                    timestamptz      NOT NULL,
        year                        int,
        transect                    text,
        period                      text,
        n_points                    int,
        median_wse_evrs_m           double precision,
        mean_wse_evrs_m             double precision,
        std_m                       double precision,
        mad_m                       double precision,
        nmad_m                      double precision,
        p05_m                       double precision,
        p95_m                       double precision,
        range_m                     double precision,
        along_track_slope_m_per_km  double precision,
        track_length_km             double precision,
        mean_stdev_water_surf_m     double precision,
        lat_mean                    double precision,
        lon_mean                    double precision,
        qc_pass                     boolean,
        qc_flags                    text,
        job_id                      uuid,
        geom                        geometry(LineString, 4326),
        PRIMARY KEY (region, date, rgt, beam)
    )""")
    op.execute("CREATE INDEX pass_levels_geom_idx ON icesat2.pass_levels USING gist (geom)")
    op.execute("CREATE INDEX pass_levels_region_dt_idx ON icesat2.pass_levels (region, datetime)")


def downgrade() -> None:
    op.execute("DROP SCHEMA icesat2 CASCADE")
