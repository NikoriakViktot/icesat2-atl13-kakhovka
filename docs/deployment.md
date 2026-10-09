# Deployment

The stack is five containers on one Linux host (Docker Compose). It needs outbound
HTTPS to SlideRule (`slideruleearth.io`), NASA CMR (via SlideRule), the PROJ CDN
(`cdn.proj.org`), AWS Open Data (`copernicus-dem-30m.s3.amazonaws.com`) and the
University of Bristol (`data.bris.ac.uk`). No inbound port except your reverse proxy.

## Requirements

| | minimum | notes |
|---|---|---|
| OS | any Linux with Docker Engine ≥ 24 | tested on Ubuntu 24.04 (WSL2) |
| Docker Compose | **≥ 2.24** | `!override` in `docker-compose.prod.yml` |
| CPU / RAM | 2 vCPU / 4 GB | ATL03 jobs and raster gridding are the heaviest; 8 GB is comfortable |
| Disk | 20 GB + data | Postgres + S3 volumes; the EGG2015 grid is 207 MB; DEM tiles 20–60 MB each |
| Access | SSH key login, `git`, `curl`, `python3` | used by `scripts/deploy_server.sh` |

## Database: the existing PostGIS (recommended)

The service does not need its own PostgreSQL. Everything it creates lives in the
schema **`icesat2`**, including its migration table (`icesat2.alembic_version`),
so it can share the platform database (`geoai-postgis-1`, database `geohydro`)
without touching Django's tables.

Once, as a superuser of that PostGIS (run it on the server):

```bash
docker exec -i geoai-postgis-1 psql -U postgres -d geohydro <<'SQL'
CREATE ROLE icesat2 LOGIN PASSWORD 'change-me';
GRANT CONNECT, CREATE ON DATABASE geohydro TO icesat2;   -- CREATE: lets it create schema icesat2
-- PostGIS is already installed in geohydro; otherwise: CREATE EXTENSION postgis;
SQL
docker inspect geoai-postgis-1 --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'
```

Then deploy with that database (the network is the one printed by `docker inspect`):

```bash
scripts/deploy_server.sh user@server \
  --db-url 'postgresql://icesat2:change-me@geoai-postgis-1:5432/geohydro' \
  --db-network geoai_default
```

Both values are written to the server's `.env` (`CONTAINER_DATABASE_URL`,
`EXTERNAL_DB_NETWORK`) and kept by later runs. The compose file
`docker-compose.external-db.yml` attaches `api`, `worker` and `migrate` to that network.
A PostGIS published on a host port works too, without a network:
`--db-url postgresql://icesat2:…@host.docker.internal:<port>/<db>`.

To read the service's tables from Django or QGIS, use the same database: schema
`icesat2` (e.g. `icesat2.atl13_pass_levels`). Grant read access to the Django role if
needed: `GRANT USAGE ON SCHEMA icesat2 TO <django_role>; GRANT SELECT ON ALL TABLES IN
SCHEMA icesat2 TO <django_role>;`.

Without `CONTAINER_DATABASE_URL` the stack starts its own PostGIS (profile `localdb`).

## One-command deploy

On the workstation:

```bash
# 1. once: allow this machine's key on the SERVER (run this ON the server)
echo 'ssh-ed25519 AAAA... niko@Niko-Workstation' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# 2. deploy / update (from the workstation)
scripts/deploy_server.sh user@server --egg /path/to/egg_2015.tif
```

The script checks git, docker and compose; clones (or fast-forwards)
`https://github.com/NikoriakViktot/icesat2-ingest` into `~/icesat2-ingest`; on the
first run writes `.env` with random secrets (API key printed once) and a matching
SeaweedFS credentials file; builds all images; starts the stack with
`docker-compose.prod.yml`; applies migrations; uploads EGG2015 (needed only for
`vertical=egg2015` regions); and waits for `/health`. Re-running it updates the code
and keeps the secrets and data.

Options: `--branch`, `--dir`, `--port` (SSH), `--egg`. `scripts/deploy_server.sh local`
runs the same steps on the machine you are on.

## Manual deploy

```bash
git clone https://github.com/NikoriakViktot/icesat2-ingest.git && cd icesat2-ingest
cp .env.example .env          # then edit: API_KEYS, POSTGRES_PASSWORD, AWS_* (see below)
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$C --profile tools build
$C up -d
$C --profile tools run --rm migrate
curl -fsS http://127.0.0.1:58000/health
```

## Configuration (`.env`)

| variable | default | meaning |
|---|---|---|
| `API_KEYS` | — | comma-separated: `key`, `name:key` (read/write) or `name:key:ro` (read-only); **required** (none = every call 401). See [frontend.md](frontend.md) |
| `CORS_ORIGINS` | empty | browser origins allowed to call the API directly, comma-separated; empty = no CORS |
| `POSTGRES_PASSWORD` | `icesat2` | used when the db volume is first created; change it **before** the first start |
| `CONTAINER_DATABASE_URL` | empty | the database **as seen from the containers**; set it to use an existing PostGIS (schema `icesat2`); empty = bundled PostGIS |
| `EXTERNAL_DB_NETWORK` | empty | Docker network of that PostGIS container (adds `docker-compose.external-db.yml`) |
| `DATABASE_URL` | localhost:55433 | the same database from the host (tools, tests); containers use `CONTAINER_DATABASE_URL` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | dev creds | S3 credentials; for SeaweedFS they must match the S3 config file |
| `AWS_ENDPOINT_URL` | `http://localhost:58333` | custom S3 endpoint; **remove** it to use AWS S3 |
| `AWS_REQUEST_CHECKSUM_CALCULATION`, `AWS_RESPONSE_CHECKSUM_VALIDATION` | `when_required` | **keep** for any non-AWS S3, or objects are stored corrupted |
| `S3_BUCKET`, `S3_PREFIX` | `icesat2`, `icesat2` | where everything is written |
| `EGG2015_URI` | `s3://icesat2/icesat2/reference/egg_2015.tif` | EGG2015 grid, `egg2015` regions only |
| `S3_BACKEND` | empty | `aws`: use AWS S3 (adds `docker-compose.aws-s3.yml`: no SeaweedFS, no endpoint override) |
| `BFF_NETWORK` | empty | Docker network of a BFF (e.g. `geoai_web`); the API joins it as `icesat2-api` (adds `docker-compose.bff-network.yml`) |
| `SEAWEED_S3_CONFIG` | `./docker/seaweedfs-s3.json` | SeaweedFS identities file (deploy script: `docker/seaweedfs-s3.local.json`) |
| `REDIS_URL` | localhost:56379 | host-side; containers use `redis://redis:6379/0` |
| `JOB_RUNNER` | `rq` | `inline` runs jobs inside the API process (tests only) |
| `BATCH_SIZE`, `FETCH_RETRIES` | 50, 3 | defaults when a job does not set them |
| `CACHE_DIR` | `/tmp/icesat2-cache` | worker cache (geoid grid, DEM tiles, PROJ grid); a volume in compose |
| `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` | — | optional; only for the earthaccess CMR fallback |
| `PROJ_NETWORK` | `ON` | lets PROJ fetch the EGM2008 grid |

## Reverse proxy (TLS)

`docker-compose.prod.yml` binds every port to `127.0.0.1`. Publish only the API,
through a proxy with TLS. Caddy (automatic Let's Encrypt):

```
# /etc/caddy/Caddyfile
icesat2.example.org {
    reverse_proxy 127.0.0.1:58000
    request_body { max_size 1MB }
}
```

nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name icesat2.example.org;
    ssl_certificate     /etc/letsencrypt/live/icesat2.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/icesat2.example.org/privkey.pem;
    client_max_body_size 1m;
    location / {
        proxy_pass http://127.0.0.1:58000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;      # raster downloads and large CSVs
    }
}
```

Never expose Postgres, S3 or Redis publicly; reach them with an SSH tunnel
(`ssh -L 55433:127.0.0.1:55433 user@server`) for QGIS / psql.

## Using AWS S3 instead of SeaweedFS

In `.env`: `S3_BACKEND=aws`, `S3_BUCKET=<bucket>`, `S3_PREFIX`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, and **delete** `AWS_ENDPOINT_URL` and
`SEAWEED_S3_CONFIG`. `scripts/deploy_server.sh` then adds `docker-compose.aws-s3.yml`, which
drops the `s3` / `s3-init` services and the SeaweedFS endpoint from the containers. The IAM
policy needs `s3:GetObject`, `PutObject`, `DeleteObject`, `ListBucket` on the bucket (prefix).

## Behind a BFF on the same host

`BFF_NETWORK=<network>` in `.env` adds `docker-compose.bff-network.yml`: the API joins that
external network as `icesat2-api`, so e.g. Django on it uses `ICESAT2_API_URL=http://icesat2-api:8000`
with its own `django:<key>` from `API_KEYS` (send only the key part in `X-API-Key`). The worker,
Redis and the database stay off that network.

## Updating

`scripts/deploy_server.sh user@server` again, or on the server:

```bash
cd ~/icesat2-ingest && git pull --ff-only
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$C --profile tools build && $C up -d && $C --profile tools run --rm migrate
```

Running jobs are interrupted when the worker restarts. They stay `running` in
`icesat2.jobs`; resubmit them (re-runs are idempotent).
