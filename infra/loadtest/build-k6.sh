#!/usr/bin/env bash
# Build and push the private k6 image just before a run: fresh synthetic-user tokens (valid
# --hours, at most 6), the question pool and the load script. The tokens are copied next to the
# Dockerfile only for the build and removed straight after.
# Run from the repo root:  bash infra/loadtest/build-k6.sh [hours]
set -euo pipefail

HOURS="${1:-4}"
TAG=loadtest-k6-1
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --profile eagleeye --query Account --output text)
REPO="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/eagleeye"

APP_ENV=loadtest S3_ENDPOINT_URL= S3_ACCESS_KEY= S3_SECRET_KEY= LLM_PROVIDER=stub \
  uv run --package eagleeye-api python scripts/loadtest_seed.py tokens --count 2000 --hours "$HOURS"

cp .loadtest/tokens.json evals/load/tokens.json
cp packages/llm/eagleeye_llm/loadtest_questions.json evals/load/loadtest_questions.json
trap 'rm -f evals/load/tokens.json' EXIT
docker build -q -t "$REPO:$TAG" evals/load >/dev/null

# ECR tags are immutable: replace the previous k6 image of the same tag
aws ecr batch-delete-image --repository-name eagleeye --image-ids imageTag="$TAG" \
  --region "$REGION" --profile eagleeye >/dev/null 2>&1 || true
aws ecr get-login-password --region "$REGION" --profile eagleeye \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com" >/dev/null
docker push -q "$REPO:$TAG"
echo "pushed $TAG (tokens valid $HOURS h)"
