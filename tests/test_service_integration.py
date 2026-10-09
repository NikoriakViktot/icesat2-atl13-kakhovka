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

from test_pipeline_steps import fake_sliderule, flat_geoid  # noqa: E402

from kakhovka_altimetry import pipeline  # noqa: E402

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

        def fake_fetch(cfg, region, granules):
            calls.append(list(granules))
            # the last granule of every batch returns nothing -> "empty"
            return fake_sliderule(granules[:-1] if len(granules) > 1 else granules)

        mp.setattr(pipeline, "fetch_batch", fake_fetch)
        mp.setattr(worker, "get_geoid", lambda settings: flat_geoid())
        yield {"dsn": dsn, "calls": calls}

    settings_mod.get_settings.cache_clear()
    mp.undo()
    moto.stop()


@pytest.fixture(scope="module")
def repo(stack):
    from kakhovka_altimetry.service.repository import Repository

    return Repository(stack["dsn"])


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
    assert stats["segments"] == 3 * 60
    assert stats["pass_levels"] == 6 and stats["pass_levels_qc"] == 6

    row = repo.get_job(job)
    assert row["status"] == "done" and row["stage"] == "load"
    statuses = [g["status"] for g in repo.list_granules("kakhovka")]
    assert sorted(statuses) == ["empty", "empty", "loaded", "loaded", "loaded"]
    assert repo.counts("kakhovka") == {"segments": 180, "pass_levels": 6}

    layout = storage.Layout(get_settings(), "kakhovka")
    assert len(storage.list_parquet(layout.raw_dir(job))) == 2

    # Crash after the load but before the granules were marked: the re-run fetches
    # and loads the same rows again; every write is an upsert -> identical counts.
    with repo.conn() as c:
        c.execute("UPDATE icesat2.granules SET status = 'pending' WHERE job_id = %s", (job,))
    stats_again = worker.run_job(job)
    assert stats_again["to_fetch"] == 5 and stats_again["segments"] == 180
    assert repo.counts("kakhovka") == {"segments": 180, "pass_levels": 6}

    # A new job over the same window skips the 5 done granules and takes the rest.
    stack["calls"].clear()
    stats2 = worker.run_job(_job(repo))
    assert stats2["already_loaded"] == 5
    assert all(g not in sum(stack["calls"], []) for g in
               [g["granule"] for g in repo.list_granules("kakhovka")][:5])

    with repo.conn() as c:
        geoms = c.execute("SELECT count(*) n FROM icesat2.pass_levels "
                          "WHERE geom IS NOT NULL").fetchone()["n"]
    assert geoms == repo.counts("kakhovka")["pass_levels"]


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

    regions = {r["slug"]: r for r in client.get("/regions", headers=h).json()}
    assert regions["kakhovka"]["pass_levels"] > 0
    assert client.get("/granules", headers=h, params={"region": "kakhovka"}).json()

    # ad-hoc region: no seed list and no CMR -> nothing to fetch, job still completes
    adhoc = {"region": {"slug": "test_lake", "refid": 1, "coord": {"lon": 30, "lat": 50},
                        "bbox": [29.9, 49.9, 30.1, 50.1]}}
    r = client.post("/jobs", headers=h, json=adhoc)
    assert r.status_code == 202
    assert client.get(f"/jobs/{r.json()['job_id']}", headers=h).json()["status"] == "done"
