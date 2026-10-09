"""multi-product: ATL08 segments, rasters, DEM comparisons, region registry

* segments / pass_levels -> atl13_segments / atl13_pass_levels, datum-neutral height
  columns (``wse_m``, ``median_wse_m``, ``mean_wse_m``) + ``vertical_datum``
* jobs / granules carry the product
* icesat2.regions: regions registered through the API
* icesat2.atl08_segments: ATL08 land/vegetation segments (partitioned by year)
* icesat2.rasters: ICESat-2 gridded DEMs written to S3 as COGs
* icesat2.dem_comparisons: ICESat-2 minus reference DEM (cop30, fabdem) per job

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

FIRST_YEAR, LAST_YEAR = 2018, 2035


def upgrade() -> None:
    # ---- ATL13 tables: product-prefixed names, datum-neutral heights ------------
    op.execute("ALTER TABLE icesat2.segments RENAME TO atl13_segments")
    for y in range(FIRST_YEAR, LAST_YEAR + 1):
        op.execute(f"ALTER TABLE icesat2.segments_{y} RENAME TO atl13_segments_{y}")
    op.execute("ALTER TABLE icesat2.segments_default RENAME TO atl13_segments_default")
    op.execute("""
        ALTER TABLE icesat2.atl13_segments
            ADD COLUMN n_m double precision,
            ADD COLUMN wse_m double precision,
            ADD COLUMN vertical_datum text,
            ADD COLUMN cop30_m double precision,
            ADD COLUMN fabdem_m double precision""")
    op.execute("""
        UPDATE icesat2.atl13_segments
        SET wse_m = h_evrs_egg2015_m, n_m = zeta_egg2015_m, vertical_datum = 'EVRS_EGG2015'""")

    op.execute("ALTER TABLE icesat2.pass_levels RENAME TO atl13_pass_levels")
    op.execute("ALTER TABLE icesat2.atl13_pass_levels "
               "RENAME COLUMN median_wse_evrs_m TO median_wse_m")
    op.execute("ALTER TABLE icesat2.atl13_pass_levels "
               "RENAME COLUMN mean_wse_evrs_m TO mean_wse_m")
    op.execute("ALTER TABLE icesat2.atl13_pass_levels ADD COLUMN vertical_datum text")
    op.execute("UPDATE icesat2.atl13_pass_levels SET vertical_datum = 'EVRS_EGG2015'")

    # ---- jobs / granules: product ----------------------------------------------
    op.execute("ALTER TABLE icesat2.jobs ADD COLUMN product text NOT NULL DEFAULT 'ATL13'")
    op.execute("ALTER TABLE icesat2.granules ADD COLUMN product text NOT NULL DEFAULT 'ATL13'")
    op.execute("ALTER TABLE icesat2.granules DROP CONSTRAINT granules_pkey")
    op.execute("ALTER TABLE icesat2.granules ADD PRIMARY KEY (region, product, granule)")

    # ---- region registry --------------------------------------------------------
    op.execute("""
    CREATE TABLE icesat2.regions (
        slug        text PRIMARY KEY,
        definition  jsonb       NOT NULL,
        footprint   geometry(Geometry, 4326),
        created_at  timestamptz NOT NULL DEFAULT now(),
        updated_at  timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX regions_footprint_idx ON icesat2.regions USING gist (footprint)")

    # ---- ATL08 ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE icesat2.atl08_segments (
        region                  text             NOT NULL,
        time                    timestamptz      NOT NULL,
        beam                    text             NOT NULL,
        granule                 text,
        rgt                     int,
        cycle                   int,
        segment_id              bigint,
        lat                     double precision NOT NULL,
        lon                     double precision NOT NULL,
        h_te_median_m           double precision,   -- ellipsoidal (WGS84)
        h_te_uncertainty_m      double precision,
        terrain_slope           double precision,
        h_canopy_m              double precision,   -- canopy height above terrain
        h_mean_canopy_m         double precision,
        h_max_canopy_m          double precision,
        h_canopy_uncertainty_m  double precision,
        canopy_openness         double precision,
        n_te_photons            int,
        n_ca_photons            int,
        segment_landcover       int,
        segment_snowcover       int,
        solar_elevation         double precision,
        n_m                     double precision,   -- geoid/quasigeoid height used
        h_m                     double precision,   -- terrain, orthometric/normal
        h_egm2008_m             double precision,   -- terrain, EGM2008 (DEM frame)
        vertical_datum          text,
        cop30_m                 double precision,
        fabdem_m                double precision,
        period                  text,
        job_id                  uuid,
        geom                    geometry(Point, 4326) NOT NULL,
        PRIMARY KEY (region, beam, time)
    ) PARTITION BY RANGE (time)""")
    for y in range(FIRST_YEAR, LAST_YEAR + 1):
        op.execute(f"""
        CREATE TABLE icesat2.atl08_segments_{y} PARTITION OF icesat2.atl08_segments
            FOR VALUES FROM ('{y}-01-01 00:00+00') TO ('{y + 1}-01-01 00:00+00')""")
    op.execute("CREATE TABLE icesat2.atl08_segments_default "
               "PARTITION OF icesat2.atl08_segments DEFAULT")
    op.execute("CREATE INDEX atl08_geom_idx ON icesat2.atl08_segments USING gist (geom)")
    op.execute("CREATE INDEX atl08_region_time_idx ON icesat2.atl08_segments (region, time)")
    op.execute("CREATE INDEX atl08_job_idx ON icesat2.atl08_segments (job_id)")

    # ---- rasters + DEM comparisons ---------------------------------------------
    op.execute("""
    CREATE TABLE icesat2.rasters (
        raster_id      uuid PRIMARY KEY,
        job_id         uuid REFERENCES icesat2.jobs (job_id),
        region         text        NOT NULL,
        product        text        NOT NULL,
        variable       text        NOT NULL,   -- dtm | chm | wse
        description    text,
        resolution_m   double precision NOT NULL,
        crs            text        NOT NULL,
        vertical_datum text,
        s3_uri         text        NOT NULL,
        stats          jsonb       NOT NULL DEFAULT '{}'::jsonb,
        footprint      geometry(Polygon, 4326),
        created_at     timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX rasters_region_idx ON icesat2.rasters (region, product, variable)")
    op.execute("CREATE INDEX rasters_footprint_idx ON icesat2.rasters USING gist (footprint)")

    op.execute("""
    CREATE TABLE icesat2.dem_comparisons (
        job_id      uuid REFERENCES icesat2.jobs (job_id),
        region      text NOT NULL,
        product     text NOT NULL,
        dem         text NOT NULL,             -- cop30 | fabdem
        height      text NOT NULL,             -- ICESat-2 column compared (EGM2008)
        n           int  NOT NULL,
        median_m    double precision,
        nmad_m      double precision,
        mean_m      double precision,
        std_m       double precision,
        rmse_m      double precision,
        p05_m       double precision,
        p95_m       double precision,
        created_at  timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (job_id, dem)
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE icesat2.dem_comparisons")
    op.execute("DROP TABLE icesat2.rasters")
    op.execute("DROP TABLE icesat2.atl08_segments")
    op.execute("DROP TABLE icesat2.regions")
    op.execute("ALTER TABLE icesat2.granules DROP CONSTRAINT granules_pkey")
    op.execute("ALTER TABLE icesat2.granules DROP COLUMN product")
    op.execute("ALTER TABLE icesat2.granules ADD PRIMARY KEY (region, granule)")
    op.execute("ALTER TABLE icesat2.jobs DROP COLUMN product")
    op.execute("ALTER TABLE icesat2.atl13_pass_levels DROP COLUMN vertical_datum")
    op.execute("ALTER TABLE icesat2.atl13_pass_levels "
               "RENAME COLUMN mean_wse_m TO mean_wse_evrs_m")
    op.execute("ALTER TABLE icesat2.atl13_pass_levels "
               "RENAME COLUMN median_wse_m TO median_wse_evrs_m")
    op.execute("ALTER TABLE icesat2.atl13_pass_levels RENAME TO pass_levels")
    op.execute("""ALTER TABLE icesat2.atl13_segments
        DROP COLUMN n_m, DROP COLUMN wse_m, DROP COLUMN vertical_datum,
        DROP COLUMN cop30_m, DROP COLUMN fabdem_m""")
    op.execute("ALTER TABLE icesat2.atl13_segments_default RENAME TO segments_default")
    for y in range(FIRST_YEAR, LAST_YEAR + 1):
        op.execute(f"ALTER TABLE icesat2.atl13_segments_{y} RENAME TO segments_{y}")
    op.execute("ALTER TABLE icesat2.atl13_segments RENAME TO segments")
