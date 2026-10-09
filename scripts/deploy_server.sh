#!/usr/bin/env bash
# Deploy (or update) the ICESat-2 ingest stack on a Linux server over SSH.
#
#   scripts/deploy_server.sh user@host [--dir icesat2-ingest] [--branch main] [--port 22]
#        [--egg /local/egg_2015.tif] [--db-url URL] [--db-network NET]
#   scripts/deploy_server.sh local ...     # same steps on this machine (no SSH)
#
# Database: --db-url points the service at an EXISTING PostGIS (as seen from inside
# the containers), e.g. postgresql://icesat2:<pw>@geoai-postgis-1:5432/geohydro with
# --db-network geoai_default (the network of that container). Without --db-url (and no
# CONTAINER_DATABASE_URL in .env) the stack runs its own PostGIS (profile localdb).
# Both values are stored in the server's .env; later runs keep them.
#
# Needs on the server: git, Docker Engine + Compose >= 2.24, this machine's public key
# in ~/.ssh/authorized_keys. First run generates .env with random secrets (API key
# printed once). Ports bind to 127.0.0.1 (docker-compose.prod.yml). docs/deployment.md.
set -euo pipefail

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
[[ $# -ge 1 && $1 != -h && $1 != --help ]] || usage 1

TARGET=$1; shift
DIR=icesat2-ingest; BRANCH=main; PORT=22; EGG=""; DB_URL=""; DB_NETWORK=""
REPO_URL=${REPO_URL:-https://github.com/NikoriakViktot/icesat2-ingest.git}
while [[ $# -gt 0 ]]; do
  case $1 in
    --dir) DIR=$2; shift 2 ;;
    --branch) BRANCH=$2; shift 2 ;;
    --port) PORT=$2; shift 2 ;;
    --egg) EGG=$2; shift 2 ;;
    --db-url) DB_URL=$2; shift 2 ;;
    --db-network) DB_NETWORK=$2; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown option $1" >&2; usage 1 ;;
  esac
done

if [[ $TARGET == local ]]; then
  SSH=(bash -c)
  copy() { cp "$1" "$DIR/$(basename "$2")"; }
  cd ~
else
  SSH=(ssh -p "$PORT" -o BatchMode=yes -o ConnectTimeout=15 "$TARGET")
  copy() { scp -q -P "$PORT" "$1" "$TARGET:$DIR/$(basename "$2")"; }
fi

# `compose` on the server: prod overrides, the external-db network when configured,
# and the bundled PostGIS only when no external database is configured.
COMPOSE_FN='compose() {
  f="-f docker-compose.yml -f docker-compose.prod.yml"
  grep -q "^EXTERNAL_DB_NETWORK=." .env && f="$f -f docker-compose.external-db.yml"
  p=""; grep -q "^CONTAINER_DATABASE_URL=." .env || p="--profile localdb"
  docker compose $f $p "$@"
}'

echo "==> checking $TARGET"
"${SSH[@]}" 'set -e
  command -v git >/dev/null || { echo "git missing on server" >&2; exit 2; }
  command -v docker >/dev/null || { echo "docker missing on server" >&2; exit 2; }
  v=$(docker compose version --short 2>/dev/null || echo 0)
  python3 - "$v" <<PY || { echo "docker compose >= 2.24 required, found $v" >&2; exit 2; }
import sys
p = [int(x) for x in sys.argv[1].lstrip("v").split(".")[:2] if x.isdigit()] + [0, 0]
sys.exit(0 if (p[0], p[1]) >= (2, 24) else 1)
PY
  echo "git $(git --version | cut -d" " -f3), docker $(docker --version | cut -d" " -f3 | tr -d ,), compose $v"'

echo "==> code ($BRANCH) -> ~/$DIR"
"${SSH[@]}" "set -e
  if [ -d '$DIR/.git' ]; then
    (cd '$DIR' && git fetch -q origin && git checkout -q '$BRANCH' && git pull -q --ff-only origin '$BRANCH')
  else
    git clone -q --branch '$BRANCH' '$REPO_URL' '$DIR'
  fi
  cd '$DIR' && git log --oneline -1"

echo "==> secrets"
"${SSH[@]}" "set -e; cd '$DIR'
  if [ -f .env ]; then echo '.env exists - kept'; exit 0; fi
  rnd() { python3 -c 'import secrets,sys; print(secrets.token_urlsafe(int(sys.argv[1])))' \$1; }
  API_KEY=\$(rnd 32); PGPW=\$(rnd 24); S3KEY=icesat2-\$(rnd 6); S3SECRET=\$(rnd 32)
  sed -e \"s|^API_KEYS=.*|API_KEYS=\$API_KEY|\" \
      -e \"s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=\$PGPW|\" \
      -e \"s|^DATABASE_URL=.*|DATABASE_URL=postgresql://icesat2:\$PGPW@localhost:55433/icesat2|\" \
      -e \"s|^AWS_ACCESS_KEY_ID=.*|AWS_ACCESS_KEY_ID=\$S3KEY|\" \
      -e \"s|^AWS_SECRET_ACCESS_KEY=.*|AWS_SECRET_ACCESS_KEY=\$S3SECRET|\" .env.example > .env
  printf '\nSEAWEED_S3_CONFIG=./docker/seaweedfs-s3.local.json\n' >> .env
  cat > docker/seaweedfs-s3.local.json <<JSON
{\"identities\": [{\"name\": \"icesat2\",
  \"credentials\": [{\"accessKey\": \"\$S3KEY\", \"secretKey\": \"\$S3SECRET\"}],
  \"actions\": [\"Admin\", \"Read\", \"Write\", \"List\", \"Tagging\"]}]}
JSON
  chmod 600 .env docker/seaweedfs-s3.local.json
  echo \"generated .env - API key (shown once, also in ~/$DIR/.env): \$API_KEY\""

if [[ -n $DB_URL || -n $DB_NETWORK ]]; then
  echo "==> database settings -> .env"
  # base64 so URLs with @ : / ? & survive the shell hops untouched
  enc() { printf '%s' "$1" | base64 -w0; }
  "${SSH[@]}" "set -e; cd '$DIR'
    python3 - '$(enc "$DB_URL")' '$(enc "$DB_NETWORK")' <<'PY'
import base64, pathlib, sys
url, net = (base64.b64decode(a).decode() for a in sys.argv[1:3])
env = pathlib.Path('.env')
lines = [l for l in env.read_text().splitlines()
         if not (url and l.startswith('CONTAINER_DATABASE_URL='))
         and not (net and l.startswith('EXTERNAL_DB_NETWORK='))]
if url:
    lines.append('CONTAINER_DATABASE_URL=' + url)
if net:
    lines.append('EXTERNAL_DB_NETWORK=' + net)
env.write_text('\n'.join(lines) + '\n')
print('database:', url.split('@')[-1] if url else '(unchanged)', '| network:', net or '(unchanged)')
PY"
fi

echo "==> build + start"
"${SSH[@]}" "set -e; cd '$DIR'; $COMPOSE_FN
  if grep -q '^CONTAINER_DATABASE_URL=.' .env; then echo 'database: external'; else echo 'database: bundled (localdb)'; fi
  compose --profile tools build -q
  compose up -d --remove-orphans
  compose --profile tools run --rm migrate
  echo \"schema at revision \$(compose --profile tools run --rm -T migrate alembic current 2>/dev/null | tail -1)\""

if [[ -n $EGG ]]; then
  echo "==> EGG2015 grid -> S3"
  copy "$EGG" .egg_2015.tif
  "${SSH[@]}" "set -e; cd '$DIR'; $COMPOSE_FN
    compose cp .egg_2015.tif api:/tmp/egg_2015.tif && rm -f .egg_2015.tif
    compose exec -T api python -c \"import os, s3fs; u = os.environ['EGG2015_URI']; \
s3fs.S3FileSystem().put('/tmp/egg_2015.tif', u.split('://', 1)[1]); print('uploaded', u)\""
fi

echo "==> health"
"${SSH[@]}" "for i in \$(seq 1 30); do curl -fsS http://127.0.0.1:58000/health && exit 0; sleep 2; done; \
  echo 'API not healthy' >&2; cd '$DIR'; $COMPOSE_FN; compose ps; exit 1"
echo
echo "done. API on the server at http://127.0.0.1:58000 (docs/deployment.md: reverse proxy)."
