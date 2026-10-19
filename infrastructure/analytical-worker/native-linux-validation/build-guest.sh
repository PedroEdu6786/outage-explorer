#!/bin/sh
set -eu
source_root=${1:-/opt/outage-runtime-validation}
report_root=${2:-/var/lib/outage-runtime-validation}
image_tag=${3:-outage-analytical-worker:validation}
cd "$source_root"
test -f pyproject.toml
test -f infrastructure/analytical-worker/Dockerfile
if test ! -e .venv/bin/python; then sudo python3 -m venv .venv; fi
test -f requirements-dev.txt
sudo sh -c '.venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir -r requirements-dev.txt > "$1/dependencies.log" 2>&1' sh "$report_root"
sudo sh -c '.venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir --no-deps --no-build-isolation . >> "$1/dependencies.log" 2>&1' sh "$report_root"
sudo sh -c 'docker build --progress plain -f infrastructure/analytical-worker/Dockerfile -t "$2" . > "$1/build.log" 2>&1' sh "$report_root" "$image_tag"
sudo docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' "$image_tag"
sudo .venv/bin/python -c 'import duckdb, pyarrow; print("DuckDB",duckdb.__version__,"PyArrow",pyarrow.__version__)'
