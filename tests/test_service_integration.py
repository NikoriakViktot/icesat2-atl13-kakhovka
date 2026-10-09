"""End-to-end service test: PostGIS (testcontainers) + S3 (moto server).

SlideRule and the EGG2015 grid are replaced by synthetic stand-ins; everything
else -- S3 layout, migrations, COPY/upsert loads, the worker stages, the API -- is
the real code. Skipped when docker is unavailable.
"""

from __future__ import annotations

import socket

import pytest

pytest.importorskip("testcontainers")
pytest.importorskip("moto")
pytest.importorskip("fastapi")

from test_pipeline_steps import fake_atl08, fake_sliderule, flat_geoid  # noqa: E402

from kakhovka_altimetry import dem, heights, pipeline  # noqa: E402

ATL08_GRANULES = ["ATL08_20210507162458_06701102_007_01.h5",
                  "ATL08_20210605150101_11121102_007_01.h5"]

API_KEY = "test-key"


def _docker_ok() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="docker not available")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def stack():
    import boto3
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from moto.server import ThreadedMotoServer
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:  # testcontainers < 4.10
        from testcontainers.postgres import PostgresContainer

    port = _free_port()
    moto = ThreadedMotoServer(ip_address="127.0.0.1", port=port)
    moto.start()
    mp = pytest.MonkeyPatch()
    endpoint = f"http://127.0.0.1:{port}"
    mp.setenv("AWS_ENDPOINT_URL", endpoint)
    mp.setenv("AWS_ACCESS_KEY_ID", "test")
    mp.setenv("AWS_SECRET_ACCESS_KEY", "test")
    mp.setenv("AWS_DEFAULT_REGION", "us-east-1")
    boto3.client("s3", endpoint_url=endpoint).create_bucket(Bucket="icesat2-test")

    with PostgresContainer("postgis/postgis:16-3.4", driver=None) as pg:
        dsn = pg.get_connection_url()
        mp.setenv("DATABASE_URL", dsn)
        mp.setenv("S3_BUCKET", "icesat2-test")
        mp.setenv("API_KEYS", API_KEY)
        mp.setenv("JOB_RUNNER", "inline")
        mp.setenv("FETCH_RETRIES", "1")
        mp.delenv("EGG2015_URI", raising=False)

        from kakhovka_altimetry.config import REPO_ROOT
        from kakhovka_altimetry.service import settings as settings_mod
        from kakhovka_altimetry.service import worker

        acfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
        acfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
        command.upgrade(acfg, "head")

        settings_mod.get_settings.cache_clear()
        calls: list[list[str]] = []

        def fake_fetch(cfg, region, granules, *, product, options=None):
            calls.append(list(granules))
            if product.name == "ATL08":
                return fake_atl08(granules)
            # the last granule of every batch returns nothing -> "empty"
            return fake_sliderule(granules[:-1] if len(granules) > 1 else granules)

        def fake_cmr(bbox, start, end, *, short_name, version):
            return ATL08_GRANULES if short_name == "ATL08" else []

        mp.setattr(pipeline, "fetch_batch", fake_fetch)
        mp.setattr(pipeline, "cmr_granules", fake_cmr)
        mp.setattr(worker, "get_geoid", lambda settings: flat_geoid())
        mp.setattr(heights, "egm2008_undulation",
                   lambda lat, lon: __import__("numpy").full(len(lat), 22.0))
        mp.setattr(dem.Cop30Source, "sample",
                   lambda self, lat, lon: __import__("numpy").full(len(lat), 40.5))
        mp.setattr(dem.FabdemSource, "sample",
                   lambda self, lat, lon: __import__("numpy").full(len(lat), 39.0))
        yield {"dsn": dsn, "calls": calls}

    settings_mod.get_settings.cache_clear()
    mp.undo()
    moto.stop()


@pytest.fixture(scope="module")
def repo(stack):
    from kakhovka_altimetry.service.repository import Repository

    return Repository(stack["dsn"])


def _counts(repo, region="kakhovka"):
    c = repo.counts(region)
    return c["atl13_segments"], c["atl13_pass_levels"]


def _job(repo, **params):
    base = {"region_slug": "kakhovka", "start": "2019-04-01", "end": "2019-06-30",
            "batch_size": 3}
    base.update(params)
    return repo.create_job("kakhovka", base)


def test_worker_end_to_end_and_idempotent(stack, repo):
    from kakhovka_altimetry.service import storage, worker
    from kakhovka_altimetry.service.settings import get_settings

    job = _job(repo, limit=5)
    stats = worker.run_job(job)
    assert stats["to_fetch"] == 5
    # batches of 3 + 2; the last granule of each batch is empty -> 3 granules with data
    assert stats["points"] == 3 * 60
    assert stats["pass_levels"] == 6 and stats["pass_levels_qc"] == 6

    row = repo.get_job(job)
    assert row["status"] == "done" and row["stage"] == "load"
    statuses = [g["status"] for g in repo.list_granules("kakhovka")]
    assert sorted(statuses) == ["empty", "empty", "loaded", "loaded", "loaded"]
    assert _counts(repo) == (180, 6)

    layout = storage.Layout(get_settings(), "kakhovka", "007", "ATL13")
    assert len(storage.list_parquet(layout.raw_dir(job))) == 2

    # Crash after the load but before the granules were marked: the re-run fetches
    # and loads the same rows again; every write is an upsert -> identical counts.
    with repo.conn() as c:
        c.execute("UPDATE icesat2.granules SET status = 'pending' WHERE job_id = %s", (job,))
    stats_again = worker.run_job(job)
    assert stats_again["to_fetch"] == 5 and stats_again["points"] == 180
    assert _counts(repo) == (180, 6)

    # A new job over the same window skips the 5 done granules and takes the rest.
    stack["calls"].clear()
    stats2 = worker.run_job(_job(repo))
    assert stats2["already_loaded"] == 5
    assert all(g not in sum(stack["calls"], []) for g in
               [g["granule"] for g in repo.list_granules("kakhovka")][:5])

    with repo.conn() as c:
        geoms = c.execute("SELECT count(*) n FROM icesat2.atl13_pass_levels "
                          "WHERE geom IS NOT NULL").fetchone()["n"]
        datums = c.execute("SELECT DISTINCT vertical_datum v FROM icesat2.atl13_segments"
                           ).fetchall()
    assert geoms == _counts(repo)[1]
    assert [d["v"] for d in datums] == ["EVRS_EGG2015"]


def test_api_flow(stack, repo):
    from fastapi.testclient import TestClient

    from kakhovka_altimetry.service.api import app

    client = TestClient(app)
    h = {"X-API-Key": API_KEY}
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/jobs").status_code == 401
    assert client.post("/jobs", json={"region_slug": "nope"}, headers=h).status_code == 404
    assert client.post("/jobs", json={}, headers=h).status_code == 422

    r = client.post("/jobs", headers=h, json={"region_slug": "kakhovka", "start": "2019-07-01",
                                               "end": "2019-07-31", "batch_size": 2})
    assert r.status_code == 202
    job = client.get(f"/jobs/{r.json()['job_id']}", headers=h).json()
    assert job["status"] == "done", job

    fc = client.get("/regions/kakhovka/pass-levels", headers=h,
                    params={"start": "2019-07-01", "end": "2019-07-31"}).json()
    assert fc["type"] == "FeatureCollection" and fc["features"]
    assert fc["features"][0]["geometry"]["type"] == "LineString"

    csv = client.get("/regions/kakhovka/pass-levels", headers=h,
                     params={"format": "csv", "qc_pass": True})
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.startswith("date,rgt,beam,datetime")
    assert "median_wse_m" in csv.text.splitlines()[0]

    regions = {r["slug"]: r for r in client.get("/regions", headers=h).json()}
    assert regions["kakhovka"]["counts"]["atl13_pass_levels"] > 0
    assert client.get("/granules", headers=h, params={"region": "kakhovka"}).json()

    # ad-hoc ATL13 region without coord -> rejected; with coord: no seed list and the
    # (faked) CMR has no ATL13 there -> nothing to fetch, the job still completes
    lake = {"slug": "test_lake", "bbox": [29.9, 49.9, 30.1, 50.1]}
    assert client.post("/jobs", headers=h, json={"region": lake}).status_code == 422
    lake["coord"] = {"lon": 30, "lat": 50}
    r = client.post("/jobs", headers=h, json={"region": lake})
    assert r.status_code == 202
    assert client.get(f"/jobs/{r.json()['job_id']}", headers=h).json()["status"] == "done"
    assert client.get("/regions/test_lake", headers=h).json()["vertical"] == "egm2008"


def test_atl08_with_dem_comparison_and_rasters(stack, repo):
    from fastapi.testclient import TestClient

    from kakhovka_altimetry.service.api import app

    client = TestClient(app)
    h = {"X-API-Key": API_KEY}
    land = {"slug": "nova_kakhovka_land", "bbox": [33.30, 46.69, 33.50, 46.75]}
    assert client.post("/regions", headers=h, json=land).status_code == 201
    assert client.post("/jobs", headers=h, json={
        "product": "ATL08", "region_slug": "nowhere"}).status_code == 404
    assert client.post("/jobs", headers=h, json={
        "product": "ATL08", "region_slug": "nova_kakhovka_land",
        "dem": {"variables": ["wse"]}}).status_code == 422

    r = client.post("/jobs", headers=h, json={
        "product": "ATL08", "region_slug": "nova_kakhovka_land",
        "start": "2021-05-01", "end": "2021-07-31",
        "compare": ["cop30", "fabdem"], "dem": {"resolution_m": 100}})
    assert r.status_code == 202, r.text
    job = client.get(f"/jobs/{r.json()['job_id']}", headers=h).json()
    assert job["status"] == "done", job["error"]
    st = job["stats"]
    assert st["product"] == "ATL08" and st["candidates"] == 2 and st["points"] > 0
    # fake ATL08: terrain 40 m (EGM2008), cop30 40.5 m, FABDEM 39 m
    assert st["dem_comparison"]["cop30"]["median_m"] == pytest.approx(-0.5)
    assert st["dem_comparison"]["fabdem"]["median_m"] == pytest.approx(1.0)
    assert {x["variable"] for x in st["rasters"]} == {"dtm", "chm"}

    pts = client.get("/regions/nova_kakhovka_land/points", headers=h,
                     params={"product": "ATL08", "format": "json"}).json()
    assert len(pts) == st["points"]
    assert pts[0]["vertical_datum"] == "EGM2008" and pts[0]["h_m"] == pytest.approx(40.0)

    cmp_rows = client.get("/dem-comparisons", headers=h,
                          params={"job_id": job["job_id"]}).json()
    assert {c["dem"] for c in cmp_rows} == {"cop30", "fabdem"}

    rasters = client.get("/rasters", headers=h,
                         params={"region": "nova_kakhovka_land"}).json()
    dtm = next(x for x in rasters if x["variable"] == "dtm")
    assert dtm["crs"] == "EPSG:32636" and dtm["footprint"]["type"] == "Polygon"
    blob = client.get(f"/rasters/{dtm['raster_id']}/download", headers=h)
    assert blob.status_code == 200 and blob.content[:2] in (b"II", b"MM")

    import io

    import rasterio
    with rasterio.open(io.BytesIO(blob.content)) as ds:
        band = ds.read(1)
        assert ds.count == 2 and abs(float(__import__("numpy").nanmedian(band)) - 40.0) < 1e-3

    products = {p["product"] for p in client.get("/products", headers=h).json()}
    assert products == {"ATL13", "ATL08", "ATL03"}
