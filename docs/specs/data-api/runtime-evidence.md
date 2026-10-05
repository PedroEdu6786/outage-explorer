# Data API Phase 1 evidence

Date: 2026-10-05. Client contract and adapter work are available; **runtime
feasibility remains pending**. No data routes, product query executor, worker
launcher, publication or deployment was enabled. The current API never imports
or executes DuckDB through these additions.

## Candidate Docker worker transport follow-up (2026-10-05)

At the user's request, the candidate analytical image now runs one bounded
stdin/stdout request using the existing DuckDB preview/query adapters. The
worker constructs digest-named paths under `/inputs`, reinspects SQL references,
preserves canonical cells, rejects malformed/duplicate/unknown input, and emits
safe errors. A narrow exact startup exception preserves the import matrix and
negative fixtures. See [build/run and protocol instructions](../../../infrastructure/analytical-worker/README.md).

Controlled transport/subprocess/architecture checks: **130 passed**. Related
HTTP transport/encoding regression: **75 passed**. Ruff lint/format, strict mypy
and whitespace checks passed. The reference-free synthetic subprocess query
returned the integer string `"42"`; a synthetic real-Parquet preview preserved
dates/decimals and rejected a missing input. The sdist/wheel build passed.
This is controlled transport evidence, not
Docker isolation, live preview or deadline/termination evidence.

The user previously reported successful restricted Alpine and analytical
dependency-image smoke runs. The updated application image has not been built
or executed by the agent. Example container/engine limits remain test settings.
The concrete `ReviewedRuntime` launcher, bounded Docker lifecycle and typed
response decoding, reviewed resource measurements and API `DataHttpResources`
wiring remain pending. HTTP preview/SQL continue to fail closed; no T1.7 check
was marked complete and no deployment or additional publication was performed.

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


## Phase 5 retained-result adapter evidence

Phase 5 reuses the unchanged-SQL inspection seam and bounded canonical encoder
inside a controlled DuckDB subprocess. Private spools contain the complete
canonical document once; a bounded offset index serves numbered/revisited pages
without engine work. Oversized cells that exceed a scratch bound at least as
large as the whole result cap produce an explicit byte-truncated prefix. Smaller
scratch budgets, unsupported representations, depth/item/schema failures still
fail explicitly rather than masquerading as byte truncation.

Fixed completion expiry, original ownership, current roles, reservations,
reader leases and autonomous expiry/dead-process cleanup are independently tested
with disposable PostgreSQL and local files. The owner advisory lock is a
process-liveness proof for private orphan cleanup, not an isolation mechanism.
No launcher is configured by this implementation; controlled deadline/busy/reap
contracts do not close actual Linux worker-tree, resource or network denial gates.
See the [Phase 5 checkpoint](tasks/phase-5.md) for exact verification results.

## Phase 6 HTTP and combined acceptance

T1.7 belongs to the user, who instructed agents to skip its validation. No Linux
launcher, credential/network denial, worker-tree limit test or representative
production measurement was run in this phase. The missing
`tests/acceptance/test_query_runtime.py` remains a runtime-evidence gap, not a
passed test. Transport implementation and controlled acceptance proceed under
that instruction.

The HTTP suite exercises real disposable PostgreSQL, migrations including 0003,
real Parquet and controlled source/S3/analytical workers. Actual response envelopes
validate against OpenAPI. It uncovered and fixed two handoff inconsistencies:
reference-free queries require nullable generation identity, and the internal
spool encoding version must not leak into the public result. The other three
tracked fixture/documentation corrections are closed with tests.

Focused PostgreSQL HTTP/refresh/coordination regression: **45 passed**. Combined
HTTP lifecycle: **2 passed**, including blocked refresh/query overlap, current
session loss, independent API reconstruction, all-grain publication, old preview
and SQL snapshot stability, and retained busy responses while health/status work.
The existing independent-process restart/fencing/recovery tests also ran in the
focused regression. Controlled transport/contract/architecture checks: **226
passed**. Dependency consistency, Ruff lint/format, strict mypy (**126 source
files**) and sdist/wheel build pass. Full configured non-live regression: **1,556 passed plus 17 subtests** in
242.16 seconds, with explicit loopback PostgreSQL and Chromium. Afterwards, the
disabled composition replaced placeholder bounds with stateless unavailable
ports; affected portable/startup and static/package gates reran. This avoids
suggesting unmeasured runtime quotas through disabled placeholder values.

### Acceptance evidence map

All rows describe controlled application/adapter evidence unless explicitly
qualified. They do not claim live provider/publication or deployment readiness.
`http` means `tests/integration/test_data_api_http.py`; `lifecycle` means
`tests/acceptance/test_data_api_lifecycle.py`; `preview`, `query`, `refresh`,
`recovery`, `coordination`, and `retention` mean the integration suites
`test_catalog_preview.py`, `test_query_results.py`, `test_refresh_execution.py`,
`test_refresh_recovery.py`, `test_data_api_postgresql.py`, and
`test_query_lifecycle.py` respectively.

| AC | Actual evidence | Remaining limit |
| --- | --- | --- |
| AC1 | http role/ownership/CSRF and current-role revocation; preview/retention continuation denial | Live identity/provider readiness remains separate. |
| AC2 | http role catalogs plus preview public projection parity | Controlled publication. |
| AC3 | preview old-generation reads with upstream unavailable; cache admits published modeled graph only | Controlled source/S3. |
| AC4 | preview inclusive/one-sided dates, binary ties, defaults; strict HTTP date-only inputs | Controlled data. |
| AC5 | preview 100/500 rows, exact fixed 15-minute expiry/revisits; http cursor-only validation | Reviewed production preview quotas remain pending. |
| AC6 | preview exact national precision; query unchanged projection/engine corpus | No live input claim. |
| AC7 | query joins/CTEs/subquery/window compatibility and unchanged SQL | Controlled DuckDB subprocess. |
| AC8 | SQL inspection adversarial corpus, role denial before inputs | OS network/file/credential isolation is user-owned T1.7 and unverified. |
| AC9 | query sequence reconstruction/revisits/direct pages; http GET never starts execution | Controlled worker. |
| AC10 | http strict pagination; retention fixed size and completion expiry | Quotas require review. |
| AC11 | http expiry/unknown IDs; preview tampering/lost continuation and retention process loss | No durable query metadata added. |
| AC12 | retention autonomous cleanup and active-reader protection | Explicit supervisor startup required. |
| AC13 | transport fixed safe error/status/retry matrix; validated success/empty/truncation fixtures | Controlled errors. |
| AC14 | http durable 202 before claim; lifecycle blocked source work | No live source admission performed. |
| AC15 | coordination frozen intervals/replays/config changes; http override rejection | Configured limits are initial allowances. |
| AC16 | lifecycle initiating-session logout and independent API reconstruction; refresh independent-process restart test | Deployed supervisor readiness not claimed. |
| AC17 | refresh conservation/exclusion/partial retention, null unknown counts; safe public quality projection | Controlled quality evidence. |
| AC18 | http latest rediscovery; coordination no-run/outage distinction; transport lookup outage | No history endpoint introduced. |
| AC19 | refresh/coordination full verified all-grain atomic publication; lifecycle new active generation | Controlled storage. |
| AC20 | preview old data/source outage; refresh failures preserve pointer; lifecycle old data during refresh | Controlled storage. |
| AC21 | lifecycle old preview and retained SQL equality after new publication | In-memory continuations require same owner process. |
| AC22 | refresh invalid/absent/partial excluded retention and disposition conservation | Controlled observations. |
| AC23 | refresh all-three-excluded retention with overlapping reasons and unchanged pointer | Controlled observations. |
| AC24 | coordination initial dates/all grains; refresh incomplete initial failure | No live initial-load proof. |
| AC25 | refresh missing/corrupt graph, source failure/resource exhaustion and no partial pointer | Controlled source/S3 failures. |
| AC26 | refresh independent worker process surviving API process restarts; lifecycle API reconstruction | Actual host supervision not configured. |
| AC27 | recovery lost owner reconciliation before terminal/replacement work | Controlled PostgreSQL races. |
| AC28 | recovery verified history after later publication without reretrieval | Controlled source/storage. |
| AC29 | recovery interrupted claim/no automatic work and explicit new-key retry | Controlled worker loss. |
| AC30 | coordination commit-loss/read failure and recovery unresolved admission occupancy | Controlled fault injection. |
| AC31 | recovery stale worker rejected during source; coordination epoch/base fencing | Controlled process/transaction barriers. |
| AC32 | query exact 1,000-row, UTF-8 byte/schema boundary and contiguous retained prefix | Controlled engine/encoder. |
| AC33 | lifecycle busy HTTP response, independent health/status; retention controlled timeout/slot/reap seam | Real ten-second worker-tree termination and measured overlap remain user-owned T1.7. |
