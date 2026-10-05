"""Controlled engine subprocess. This fixture is NOT an OS sandbox."""

import pickle
import sys

from outage_explorer.entrypoints.query_worker import run_preview
from outage_explorer.infrastructure.duckdb.previews import execute_preview

request, bounds = pickle.loads(sys.stdin.buffer.read())
try:
    result = run_preview(request, lambda request: execute_preview(request, bounds))
except Exception as error:
    result = error
sys.stdout.buffer.write(pickle.dumps(result))
