"""Synthetic test subprocess; deliberately makes no OS isolation claim."""

import pickle
import sys

from outage_explorer.infrastructure.duckdb.queries import execute_query

request, bounds, encoding = pickle.loads(sys.stdin.buffer.read())
try:
    output = execute_query(request, bounds, encoding)
except Exception as error:
    output = error
sys.stdout.buffer.write(pickle.dumps(output))
