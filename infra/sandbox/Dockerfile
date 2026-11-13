# Analysis sandbox (C6 §4). Runs model-written DuckDB SQL or Python with no network,
# a read-only root filesystem and resource caps set by the caller (docker_executor.py).
#   docker build -t eagleeye-sandbox:1 infra/sandbox
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

# Debian security updates on top of the base image (e.g. zlib); rebuild periodically
RUN apt-get update \
    && apt-get -y upgrade \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /opt/requirements.txt
RUN pip install --no-cache-dir -r /opt/requirements.txt

COPY runner.py /opt/runner.py
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox
USER 10001
WORKDIR /work

ENTRYPOINT ["python", "/opt/runner.py"]
