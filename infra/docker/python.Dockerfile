# The image for the Python services. By default it contains all four (SERVICE=all) and the
# container's SERVICE environment variable picks which one starts:
#   api | gateway | agent-worker | ingest-worker
# One image means one pull when the demo machine wakes and one copy in the registry (the
# services share almost all their libraries). A single-service image is still possible:
#
#   docker build -f infra/docker/python.Dockerfile -t eagleeye:local .
#   docker build -f infra/docker/python.Dockerfile --build-arg SERVICE=api -t eagleeye-api:local .
#
# Build stage: uv installs the services and their workspace packages (non-editable, locked
# versions) into /opt/venv. Runtime stage: slim Python, that venv, non-root user.
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.10.3 /uv /bin/uv
ARG SERVICE=all
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY apps/ apps/
RUN case "$SERVICE" in \
      all) target="--all-packages" ;; \
      api) target="--package eagleeye-api" ;; \
      gateway) target="--package eagleeye-data-gateway" ;; \
      agent-worker) target="--package eagleeye-agent-worker" ;; \
      ingest-worker) target="--package eagleeye-ingest-worker" ;; \
      *) echo "SERVICE must be all, api, gateway, agent-worker or ingest-worker" >&2; exit 1 ;; \
    esac \
    && uv sync --frozen --no-dev --no-editable $target

FROM python:${PYTHON_VERSION}-slim AS runtime
ARG SERVICE=all
# Debian security updates on top of the base image; rebuild periodically
RUN apt-get update \
    && apt-get -y upgrade \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin eagleeye
COPY --from=build /opt/venv /opt/venv
COPY infra/docker/entrypoint.sh /usr/local/bin/eagleeye-entrypoint
COPY infra/docker/healthcheck.py /usr/local/bin/eagleeye-healthcheck
# the API seeds the shared demo account from these files (python -m app.demo setup|reset)
COPY Trial/data/data-files /app/Trial/data/data-files
# with SERVICE=all the container sets SERVICE at run time (compose / the ECS task definition)
ENV SERVICE=${SERVICE} \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/eagleeye
WORKDIR /app
USER 10001
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "/usr/local/bin/eagleeye-healthcheck"]
ENTRYPOINT ["sh", "/usr/local/bin/eagleeye-entrypoint"]
