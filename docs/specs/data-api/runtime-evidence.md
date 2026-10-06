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
| AC8 | SQL inspection adversarial corpus, role denial before inputs; native Linux synthetic isolation probes | Full user-owned T1.7 measurement/review remains open. |
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
| AC33 | lifecycle busy HTTP response, independent health/status; retention controlled timeout/slot/reap seam; native Linux deadline/descendant/recovery probes | Representative measured overlap and full T1.7 review remain open. |

## Partial native Linux analytical validation — October 5, 2026

Explicitly approved synthetic validation ran inside a dedicated Colima
`outage-runtime` VM: Ubuntu 24.04.4/kernel 6.8.0-117-generic, Linux/arm64,
Docker 29.5.2, DuckDB 1.5.6 and PyArrow 25.0.1. The VM has candidate 4 CPUs/6 GiB
RAM/20 GiB data disk; these values are not measured product budgets. The controller
runs as 65534:65534 with trusted daemon-group access; workers receive no socket,
host credentials or privileges. Desktop context remains `desktop-linux` and the
existing default Colima profile remains stopped.

The approved invocation ran the reviewed
[run helper](../../../infrastructure/analytical-worker/native-linux-validation/run-isolation.sh)
inside the guest: exact `-m runtime_docker`, clean environment, nonsecret candidate
profile and actual immutable image. Final execution: **19 passed, one representative
measurement test deselected, 21.29 seconds**. A focused Linux execute-only ancestor
regression passed. The initial real setup failures uncovered a secure traversal
bug; it was fixed without widening filesystem permissions, then the image was
rebuilt and all probes rerun.

- Image: `sha256:553111d33d88c52344317ee9a75893fc65be4093362c7c79b9c93b9aeb973ff4`.
- Profile: `261ad952916d7334a0e90afac3bbc23a961fd82db2ef29d0147243f9415db7bd`.
- [Current unreviewed directory-mount isolation evidence](../analytical-runtime/evidence/2026-10-05-colima-isolation-directory-mount.json),
  matching image `sha256:1ee90c05fa1c8578b3240f4eb39382103fe948f190d9ec0b8e3593440cd9b176`
  and profile `a227d729593bcff61f301df141e2479301c7cf9fbf91ea0ebe8891c33611f57f`.
  This is synthetic isolation evidence only; no performance measurements were run.
- [Historical unreviewed evidence bundle](../analytical-runtime/evidence/2026-10-05-colima-isolation.json),
  SHA-256 `4312d0dff3c3c1b0eb3c959195690b8090cba9af8f5b49061fd8616948e483ad`.
- Actual spill filesystem: 16,494,592 allocatable bytes; 1,024 inodes.
- Final cleanup: zero owned containers, spill execution directories and recovery
  ledgers; only the owned pool lock file remains.

Actual probes verified canonical transport, namespace/network/mount/environment
denial, immutable authorized staging, cgroup controls, CPU throttling, memory/PID
exhaustion, aggregate/open-unlinked disk and inode exhaustion, noexec, deadlines,
crashes, child termination, cancellation, bounded I/O, failed reap, restart and
ambiguous creation. No protected production input or product API was used.

**This is partial evidence, not reviewed readiness:** representative old/current
public inputs, independently authorized existing refresh/API overlap, S3 transfer/
storage evidence and measured-budget review remain missing. Original T1.7/T1.C,
analytical T4.3/T4.C and separate Phase 5 API enablement remain open. No source
refresh, publication, PostgreSQL changes, cloud deployment or API enablement ran.

## Representative measurement continuation and failed readiness review — October 5

The existing local connector candidate `56aed8d8f2034071875468cc32c3a6f9`
(manifest `f74027258fdbf78ba040128b4761166c15249177365df4eba7db1bd5f5232cd0`)
and refresh candidate `99af365f-c549-49bc-9ccc-c6b70d838d9f`
(manifest `27e8b47f7d904d6aa4991637f1effc915cf668ccfcdb02a2080d1eab02b88ad2`)
were revalidated locally, then projected through the same modeled domain decoder,
schema and public column mapping as the product cache. This verified manifest and
modeled digests/sizes/schema/rows/keys/days, not full raw/disposition graph replay
or publication. No source retrieval ran. Only the resulting public files and
contributor harness were copied to the existing guest; no credentials transferred.
The [preparation record](../analytical-runtime/evidence/2026-10-05-public-input-preparation.json)
is unreviewed and contains no public cells or private configuration.

| Public grain (each snapshot) | Daily files | Rows | Entities | Public bytes |
| --- | ---: | ---: | ---: | ---: |
| National | 183 | 183 | 1 | 593,718 |
| Facilities | 183 | 10,065 | 55 | 744,980 |
| Generators | 183 | 17,385 | 95 | 860,649 |

Both cover April 2–October 1 inclusive and all 549 public hashes match. Keeping
their partition layout produced a 274,689-byte descriptor manifest; the former
64-KiB harness cap was insufficient. The corrected 1-MiB manifest bound retains
independent file/cache limits; evidence reports remain bounded to 64 KiB. No
image/profile change was needed for this contributor-harness correction.

Actual guest invocation used the original nonsecret `candidate.json`, clean
environment, controller 65534:65534 with Docker supplementary group, the existing
checkout and `run-analytical-only.py --inputs` pointing at the verified public
snapshot manifest. The partial mode makes zero health/refresh/source requests.
The final invocation occurred October 6, 04:02 UTC (October 5 local time).
The [failed measurement report](../analytical-runtime/evidence/2026-10-05-colima-measurements-failed.json)
SHA-256 is `27982988121795e0f3fb55f00ec290d7ea695bc2965ac772b19c18644b56720b`.
It matches the original image/profile above and records a concrete admission
failure: **141,646 mount argv bytes exceed the 131,072-byte controller cap** for
549 authorized files. The worker JSON request was 58,458 bytes and fit its bound.
This is candidate controller insufficiency; no larger allowance was invented.

The real local-copy stage transferred 2,199,347 public bytes in 0.044035125
seconds. Ten numeric host/storage samples succeeded; sampled cache/staging maxima
were each 2,199,347 bytes and minimum host `MemAvailable` was 5,704,568,832 bytes.
These are partial local preparation measurements, not S3 transfer, guaranteed
peaks or complete worker budgets. No container launched; zero container memory,
CPU, spool/index or API/refresh fields mean unobserved coverage. SQL/encoding/
pagination/cold-warm execution and representative spill remain unmeasured.
Cleanup passed; [final owned-resource verification](../analytical-runtime/evidence/2026-10-05-colima-measurement-cleanup.json)
found zero owned containers, spill execution directories, recovery ledgers and
staging/cache/result entries on the unchanged image/profile.

Read-only workload discovery found no API/refresh process in the Linux guest.
On the contributor Mac, PID 38632 listened on `127.0.0.1:8000` and `/health`
returned `ok`/`outage-explorer` at `2026-10-06T03:59:01.885311Z`; child PID 38744
had no listener and was not established as an active refresh. No process arguments
or environment were inspected. These Darwin processes cannot supply Linux
co-located resource sampling. Existing historical connector S3 records under
`/private/tmp/outage-phase6-evidence/` contain elapsed/RSS/object/graph/staging
measurements, but lack matching interval/start ticks, observed transfer bytes,
spill/cache/refresh peaks and collector metadata. They cannot close overlap/S3
coverage for this execution. No new refresh or publication was initiated.

| T4.C gate / open decision | Review outcome |
| --- | --- |
| Exact image/profile/daemon, synthetic isolation and termination | Prior 19 real probes match unchanged candidate; evidence remains unreviewed. |
| Dedicated ext4 aggregate/inode/noexec enforcement | Prior matching real probes passed; representative query spill high-water coverage missing. |
| Genuine partitioned old/current public inputs | Prepared and verified from existing candidates; identical public content and representativeness/publication limitations require review. |
| Supported input admission and preparation/controller bounds | Failed: 141,646 mount argv bytes exceed 131,072; worker request fits. |
| Cold/warm query, encoding, retained old result, spool/index, paging | Not completed after admission failure; local-copy cold cannot replace product S3 cold. |
| Container/host/API/refresh resource and latency overlap | Partial host/storage only; no Linux workload pair or container samples. |
| S3 transfer/cache/refresh/spill correlated numeric record | Missing; historical records have unmatched scope and incomplete fields. |
| Measured memory/CPU/process/temp/cache/output/retention/deadlines | Candidate values remain unapproved; successful execution and overlap measurements required. |
| API owner/supervisor topology and recovery-ledger storage | Proposed local single-owner configuration has controlled/isolated evidence; operational topology/storage choice remains unreviewed. |
| Evidence reviewer and invalidation | Profile-bound implementation exists; no approval/reviewer was fabricated. Image/profile changes require affected evidence reruns. |
| SQL parser wall-clock enforcement | Remains open in the plan; parser/static controlled checks do not resolve host wall-clock enforcement. |

**T4.C review does not pass.** T4.3, T4.C and original data-API T1.7/T1.C stay
open. Existing isolation evidence is preserved; this failed report adds matching
evidence rather than replacing it. Preview/SQL remain disabled and Phase 5 still
requires complete readiness plus explicit enablement direction.
