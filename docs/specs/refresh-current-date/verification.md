# Verification — 2026-10-07

- Controlled refresh suite with disposable loopback PostgreSQL, fake EIA/S3 and
  real Parquet: **100 passed**. Includes a subsequent 189-day HTTP admission
  through verified publication, preserving the frozen source/model interval.
- Connector, HTTP transport and architecture checks: **429 passed**.
- Unit admission coverage proves startup does not resolve today, UTC conversion,
  midnight advancement for new keys, replay before clock resolution, future-start
  rejection, denied/overridden requests before clock access, strict start parsing,
  legacy settings ignored and a 1,011-day domain configuration accepted only for
  subsequent runs. These cases are included in the refresh suite.
- Ruff lint and format checks passed (452 Python files); strict mypy passed
  (148 source files); whitespace checks passed.

The initial database invocation used a nonexistent local role; rerunning with the
cluster's test role completed successfully. A new test initially expected one
source data request per grain; the adapter also performs its existing verification
probe. The test now checks all three requested routes and their exact intervals.

No live EIA/AWS calls, API/worker restarts or real publication were performed.
This does not establish capacity for arbitrary historical ranges. Finite resource
budgets and the explicit initial-load interval remain enforced. Concurrent preview
filter changes were present during testing and are excluded from this commit.
