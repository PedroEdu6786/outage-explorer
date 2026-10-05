# Data API Phase 1 evidence

Date: 2026-10-05. Client contract and adapter work are available; **runtime
feasibility remains pending**. No data routes, product query executor, worker
launcher, publication or deployment was enabled. The current API never imports
or executes DuckDB through these additions.

## Controlled compatibility profile

Pinned DuckDB 1.5.6, SQLGlot 30.21.0 and pytz 2026.2. Actual timestamptz fetches
require pytz. JSON Schema validation uses jsonschema 4.26.0. Dependencies were
installed in the local Python 3.14 environment; Python 3.12 remains a CI target,
not a locally verified claim.

`tests/fixtures/data_api/engine_probe.py` is a controlled test subprocess. It
creates synthetic in-memory relations, disables external access and extension
autoload/install, sets one engine thread and 128 MB engine memory, then checks
joins, aggregates, scoped/shadowing/recursive CTEs, sets, subqueries, windows,
unchanged ORDER/LIMIT/OFFSET and actual scalar/nested serialization. This process
is **not an OS sandbox**, has no production entry point, and proves no file,
network, credential or process-escape isolation.

Function capabilities are frozen from the pinned engine's built-in internal
scalar/aggregate metadata, normalized with the pinned parser, plus language/window
constructs and pure random/UUID generation. Side effects, extensions, macros,
table functions, qualified functions and unknown functions fail closed.
Additional exclusions cover environment/config/catalog identity, SQL-in-string
plan/serialization functions, search-path inspection and internal-prefixed
functions. Engine `has_side_effects=false` is not a security proof. Scope analysis
collects even unused CTE dependencies; the application must authorize all grains.
A reference-free query is explicitly identified and still requires a recognized
current role; no execution/authorization bypass is supplied.

SQL parser test settings: 65,536 UTF-8 input bytes, 10,000 AST nodes, depth 100.
Encoding test settings: 1 MiB/cell, depth 16, 10,000 nested items, 100 columns,
64 KiB schema; metadata is bounded before recursive expansion and nested cells
charge cumulative encoded bytes. These are reproducible **test settings**, not
measured production budgets. Parsing itself still needs a separately enforced
wall-clock/CPU boundary; input/AST caps do not provide that deadline.

Verified encoding covers engine integer types through HUGEINT (as strings), decimal128,
finite/nonfinite float, booleans/null, date, timezone-free time/timestamp,
UTC-normalized instants, binary, lists, structs and maps. Python's normal
nanosecond timestamp conversion loses precision and interval conversion loses
calendar months; those types fail explicitly. Time-with-timezone, union/variant,
fixed arrays, BIGNUM, UUID and enum are also unverified. Add evidence before advertising
these output types. Actual DATE/TIMESTAMP infinity fetches map to Python min/max
finite sentinels, so these ambiguous temporal extremes are explicitly rejected
(including finite values at the same endpoints). This is a documented compatibility
limitation, not permission
to coerce values to strings or silently change SQL.

Primary API references consulted: [DuckDB Python types](https://duckdb.org/docs/current/clients/python/types),
[DuckDB conversion](https://duckdb.org/docs/current/clients/python/conversion),
[SQLGlot scope implementation](https://github.com/tobymao/sqlglot/blob/main/sqlglot/optimizer/scope.py).
Actual pinned adapter tests govern local compatibility, not the moving latest docs.

## Environment and open gate

`uname -s` returned `Darwin`. `docker info --format '{{.OSType}}'` failed because
`/Users/PECRUZ/.docker/run/docker.sock` does not exist; no accessible Linux Docker
daemon was available. No suitable Linux runtime was provisioned or assumed.

T1.7 remains incomplete. A concrete Linux launcher must demonstrate:

1. Only approved modeled inputs are readable; operational DB, application files,
   credentials, raw/provenance graphs and network access are denied.
2. Enforced hard memory/process/private disk limits, full process-group deadline
   termination/reaping, no surviving child and safe cleanup on failure.
3. Cold/warm preparation, result encoding/spool/index, old-generation pinning and
   concurrent refresh/query/API resource measurements on representative input.
4. Reviewed preparation/overall deadlines, cache/spill/output and retention quotas,
   supervision and API ownership. Three results/user and ten/global remain proposals.

Do not activate product SQL or mark AC8/AC33 complete based on this test subprocess,
static checks, engine configuration or schema fixtures. Independent downstream
contract/domain work can proceed while the runtime checkpoint stays open.

## Verification results

`make check` completed successfully: dependency consistency, Ruff lint/format,
mypy (84 source files), 1,244 passed / 25 skipped tests, and sdist/wheel build.
Skipped tests require an explicitly configured disposable PostgreSQL instance;
no operational storage was changed by this phase. Four temporal-extreme cases
were added after full-suite collection; the final affected encoding/engine suite
was run separately (22 passed), with final Ruff/format/mypy/diff checks clean.
The earlier focused contract/projection/parser/encoding/engine/architecture run
passed 222 tests. This evidence does not close T1.7 or claim live endpoint behavior.
