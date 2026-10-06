#!/bin/sh
set -eu
cd /opt/outage-runtime-validation
sudo test -f /var/lib/outage-runtime-validation/candidate.json
docker_group=$(stat -c %g /run/docker.sock)
sudo setpriv --reuid=65534 --regid=65534 --groups="$docker_group" \
  env -i PATH=/usr/bin:/bin HOME=/nonexistent PYTHONDONTWRITEBYTECODE=1 \
  OUTAGE_RUNTIME_TEST_PROFILE=/var/lib/outage-runtime-validation/candidate.json \
  OUTAGE_RUNTIME_DOCKER_EXECUTABLE=/usr/bin/docker \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/acceptance/test_query_runtime.py -m runtime_docker
