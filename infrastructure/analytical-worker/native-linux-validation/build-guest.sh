#!/bin/sh
set -eu
cd /opt/outage-runtime-validation
test -f pyproject.toml
test -f infrastructure/analytical-worker/Dockerfile
if test ! -e .venv/bin/python; then sudo python3 -m venv .venv; fi
test -f requirements-dev.txt
sudo sh -c '.venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir -r requirements-dev.txt > /var/lib/outage-runtime-validation/dependencies.log 2>&1'
sudo sh -c '.venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir --no-deps --no-build-isolation . >> /var/lib/outage-runtime-validation/dependencies.log 2>&1'
sudo sh -c 'docker build --progress plain -f infrastructure/analytical-worker/Dockerfile -t outage-analytical-worker:validation . > /var/lib/outage-runtime-validation/build.log 2>&1'
sudo docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' outage-analytical-worker:validation
sudo .venv/bin/python -c 'import duckdb, pyarrow; print("DuckDB",duckdb.__version__,"PyArrow",pyarrow.__version__)'
