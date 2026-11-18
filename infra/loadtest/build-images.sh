#!/usr/bin/env bash
# Build the load-test images (Phase 7C) with their data already inside, so Fargate tasks start
# in seconds instead of restoring gigabytes:
#   appdb      Supabase Postgres + supabase/migrations + the warehouse catalog (copied read-only
#              from the demo database) + 2,000 synthetic users + the two video accounts
#   warehouse  Postgres 16 + the Grand Line data (dumped from the local warehouse container)
#   k6         the load script, question pool and tokens (built by build-k6.sh, run near the test)
#
# Needs: Docker, the local warehouse container (eagleeye-warehouse-1), .env.cloud (the demo's
# DATABASE_URL, read only for the catalog copy), VIDEO_ADMIN_CLERK_ID / VIDEO_MEMBER_CLERK_ID.
# Run from the repo root:  bash infra/loadtest/build-images.sh [appdb|warehouse|all] [--push]
set -euo pipefail

WHAT="${1:-all}"
PUSH="${2:-}"
KEYS=.loadtest
SUPA_IMAGE=public.ecr.aws/supabase/postgres:17.11.0.006
PG_IMAGE=postgres:16-alpine
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --profile eagleeye --query Account --output text)
ECR="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/eagleeye"
APPDB_TAG=loadtest-appdb-1
WAREHOUSE_TAG=loadtest-warehouse-1
CATALOG_TABLES="data_sources source_grants catalog_tables catalog_columns catalog_metrics catalog_examples"
export MSYS_NO_PATHCONV=1  # Git Bash: leave container paths alone

mkdir -p "$KEYS"
if [ ! -s "$KEYS/db_password" ]; then
  python -c "import secrets; print(secrets.token_urlsafe(24).replace('-', 'x').replace('_', 'y'))" > "$KEYS/db_password"
  chmod 600 "$KEYS/db_password"
fi
PW=$(cat "$KEYS/db_password")

wait_ready() {  # container, user, db
  for _ in $(seq 1 90); do
    if docker exec "$1" pg_isready -U "$2" -d "$3" -h 127.0.0.1 >/dev/null 2>&1; then sleep 3; return 0; fi
    sleep 2
  done
  echo "database in $1 did not start" >&2; docker logs --tail 40 "$1" >&2; return 1
}

build_appdb() {
  docker rm -f lt-appdb >/dev/null 2>&1 || true
  docker run -d --name lt-appdb -e POSTGRES_PASSWORD="$PW" -p 127.0.0.1:55432:5432 "$SUPA_IMAGE" >/dev/null
  wait_ready lt-appdb postgres postgres
  echo "applying $(ls supabase/migrations/*.sql | wc -l) migrations"
  for f in supabase/migrations/*.sql; do
    docker exec -i lt-appdb psql -q -U supabase_admin -d postgres -h 127.0.0.1 -v ON_ERROR_STOP=1 < "$f" >/dev/null
  done

  echo "copying the warehouse catalog from the demo database (read only)"
  local args=""
  for t in $CATALOG_TABLES; do args="$args -t public.$t"; done
  # the URL stays in the environment: never echoed or written to disk
  DEMO_DB_URL=$(python -c "import re; l=[x for x in open('.env.cloud', encoding='utf-8') if x.startswith('DATABASE_URL=')][0]; print(re.split(r'\s', l.split('=', 1)[1].strip().strip(chr(34)))[0])")  # drops an inline comment
  docker exec -e PGURL="$DEMO_DB_URL" lt-appdb sh -c "pg_dump \"\$PGURL\" --data-only --no-owner --no-privileges $args" \
    | docker exec -i lt-appdb psql -q -U supabase_admin -d postgres -h 127.0.0.1 -v ON_ERROR_STOP=1 >/dev/null
  unset DEMO_DB_URL
  docker exec lt-appdb psql -U supabase_admin -d postgres -h 127.0.0.1 -Atc \
    "select 'catalog: ' || (select count(*) from data_sources) || ' sources, ' || (select count(*) from catalog_tables) || ' tables, ' || (select count(*) from catalog_columns) || ' columns'"

  echo "seeding synthetic users and the video accounts"
  export APP_ENV=loadtest S3_ENDPOINT_URL= S3_ACCESS_KEY= S3_SECRET_KEY= LLM_PROVIDER=stub
  export DATABASE_URL="postgresql://postgres:$PW@127.0.0.1:55432/postgres"
  uv run --package eagleeye-api python scripts/loadtest_seed.py users --count 2000 --hours 1 --confirm-db-host 127.0.0.1
  uv run --package eagleeye-api python scripts/loadtest_seed.py video-accounts \
    --admin-clerk-id "$VIDEO_ADMIN_CLERK_ID" --member-clerk-id "$VIDEO_MEMBER_CLERK_ID" --confirm-db-host 127.0.0.1
  rm -f "$KEYS/tokens.json"  # signed again just before the run (tokens command)

  docker stop -t 60 lt-appdb >/dev/null  # clean shutdown: the data folder is consistent
  docker commit lt-appdb "$ECR:$APPDB_TAG" >/dev/null
  docker rm lt-appdb >/dev/null
  echo "built $APPDB_TAG"
}

build_warehouse() {
  docker start eagleeye-warehouse-1 >/dev/null
  wait_ready eagleeye-warehouse-1 warehouse_admin warehouse
  docker rm -f lt-warehouse >/dev/null 2>&1 || true
  # PGDATA outside the image's declared volume, so `docker commit` keeps the data
  docker run -d --name lt-warehouse -e PGDATA=/pgdata -e POSTGRES_DB=warehouse \
    -e POSTGRES_USER=warehouse_admin -e POSTGRES_PASSWORD="$PW" \
    -v "$(pwd -W 2>/dev/null || pwd)/infra/warehouse/init/02_roles.sql:/roles.sql:ro" "$PG_IMAGE" >/dev/null
  wait_ready lt-warehouse warehouse_admin warehouse
  echo "copying the Grand Line data (about 2 GB)"
  docker exec eagleeye-warehouse-1 pg_dump -U warehouse_admin -d warehouse --no-owner --no-privileges \
    -n network -n commercial -n equipment -n finance -n operations -n hr \
    | docker exec -i lt-warehouse psql -q -U warehouse_admin -d warehouse -v ON_ERROR_STOP=1 >/dev/null
  docker exec lt-warehouse psql -q -U warehouse_admin -d warehouse -v ON_ERROR_STOP=1 -f /roles.sql >/dev/null
  docker exec lt-warehouse psql -U warehouse_admin -d warehouse -Atc "analyze" >/dev/null
  docker exec lt-warehouse psql -U warehouse_admin -d warehouse -Atc \
    "select 'warehouse: ' || count(*) || ' tables, ' || pg_size_pretty(pg_database_size('warehouse')) from information_schema.tables where table_schema in ('network','commercial','equipment','finance','operations','hr')"
  docker stop -t 60 lt-warehouse >/dev/null
  docker commit --change "ENV PGDATA=/pgdata" lt-warehouse "$ECR:$WAREHOUSE_TAG" >/dev/null
  docker rm lt-warehouse >/dev/null
  echo "built $WAREHOUSE_TAG"
}

push() {
  aws ecr get-login-password --region "$REGION" --profile eagleeye \
    | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com" >/dev/null
  for tag in "$@"; do docker push -q "$ECR:$tag"; done
}

case "$WHAT" in
  appdb) build_appdb; [ "$PUSH" = "--push" ] && push "$APPDB_TAG" ;;
  warehouse) build_warehouse; [ "$PUSH" = "--push" ] && push "$WAREHOUSE_TAG" ;;
  all) build_appdb; build_warehouse; [ "$PUSH" = "--push" ] && push "$APPDB_TAG" "$WAREHOUSE_TAG" ;;
  *) echo "usage: $0 [appdb|warehouse|all] [--push]" >&2; exit 2 ;;
esac
