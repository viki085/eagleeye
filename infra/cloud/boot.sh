#!/bin/bash
# The demo machine's start-up (Phase 7B), run at every boot by eagleeye.service after it has
# synced this bundle from S3, so changes here apply at the next start without a new machine.
# /opt/eagleeye/machine.env (written once at first boot) provides REGION, ACCOUNT_ID, SSM_ENV,
# SSM_ROOT and DEPLOY_BUCKET.
set -euo pipefail
# shellcheck source=/dev/null
. /opt/eagleeye/machine.env
cd /opt/eagleeye
registry="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

retry() { # retry <attempts> <command...>: networks and registries have bad moments
  local n=$1 i
  shift
  for ((i = 1; i <= n; i++)); do
    "$@" && return 0
    echo "eagleeye: attempt $i/$n failed: $*" >&2
    sleep $((i * 10))
  done
  return 1
}

# the bundle holds no secrets, and containers read parts of it as their own users (Postgres
# runs the warehouse init scripts as "postgres"), so it must be readable by everyone
chmod -R a+rX /opt/eagleeye/repo

# settings: every parameter under the env path, NAME=VALUE
umask 077
retry 3 aws ssm get-parameters-by-path --region "$REGION" --path "$SSM_ENV" --recursive \
  --with-decryption --query 'Parameters[].[Name,Value]' --output text > .params.tsv
while IFS=$'\t' read -r name value; do echo "${name##*/}=$value"; done < .params.tsv > .env.demo.new
rm -f .params.tsv
# AWS mode for object storage: no endpoint and no keys = the machine's role
printf 'S3_ENDPOINT_URL=\nS3_ACCESS_KEY=\nS3_SECRET_KEY=\n' >> .env.demo.new
mv .env.demo.new .env.demo

tag=$(retry 3 aws ssm get-parameter --region "$REGION" --name "$SSM_ROOT/image_tag" \
  --query Parameter.Value --output text)
if [ "$tag" = "none" ]; then
  echo "eagleeye: nothing deployed yet (image_tag is none)"
  exit 0
fi
echo "$registry/eagleeye:$tag" > /opt/eagleeye/image
ecr_login() {
  aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "$registry"
}
retry 3 ecr_login
# the disk is small (20 GB) and each image is a few GB: drop images no container uses before
# pulling (a full disk fails the pull and the demo stays down), and again after the start
docker image prune -af >/dev/null || true
retry 3 eagleeye-compose pull --quiet
eagleeye-compose up -d --remove-orphans
docker image prune -af >/dev/null || true

# the warehouse's read-only role gets this deployment's password (its init file has a local one)
ro=$(grep '^WAREHOUSE_RO_PASSWORD=' .env.demo | cut -d= -f2-)
for _ in $(seq 1 30); do
  if eagleeye-compose exec -T warehouse pg_isready -U warehouse_admin -d warehouse >/dev/null; then
    eagleeye-compose exec -T warehouse psql -q -U warehouse_admin -d warehouse \
      -v ON_ERROR_STOP=1 -c "ALTER ROLE eagleeye_ro PASSWORD '$ro'"
    break
  fi
  sleep 5
done
echo "eagleeye: started $tag"
