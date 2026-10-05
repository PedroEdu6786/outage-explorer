# Plan: Docker analytical runtime

> Status: draft design; no runtime enablement · Slug: analytical-runtime · Spec: [spec.md](spec.md)

## Approach

Implement a Docker adapter behind `ReviewedRuntime`, with trusted host preparation
and one private request per container. Reuse the existing application services,
cache, cursor and result stores through `DataHttpResources`; add explicit
supervisor ownership rather than starting anything in an HTTP factory. All
choices below are proposed implementation details within existing accepted
boundaries, pending their checks and evidence. (FR1–FR12, TR1–TR6)

Authority: [data-api plan](../data-api/plan.md), [HTTP contract](../data-api/http-contract.md),
[ADR-0007](../../adr/0007-bounded-parquet-query-execution.md),
[ADR-0008](../../adr/0008-local-parquet-file-cache.md),
[ADR-0013](../../adr/0013-initial-query-controls.md),
[ADR-0015](../../adr/0015-dataset-preview-pagination.md),
[ADR-0020](../../adr/0020-paginate-query-results.md),
[ADR-0021](../../adr/0021-number-query-result-pages.md),
[ADR-0022](../../adr/0022-ephemeral-query-pagination-state.md),
[ADR-0030](../../adr/0030-layered-flask-monolith.md),
[ADR-0032](../../adr/0032-postgresql-on-rds.md),
[ADR-0038](../../adr/0038-ec2-deployment-local-development.md),
[ADR-0043](../../adr/0043-seeded-users-and-role-only-access.md),
[ADR-0044](../../adr/0044-one-role-per-user.md) and
[ADR-0052](../../adr/0052-interrupted-refresh-recovery.md).

## Components affected and current seams

| Existing component | Reuse and remaining work | Requirements |
| --- | --- | --- |
| `worker_runtime/launcher.py` | `VerifiedLauncher` reserves one slot; runtime must enforce bounds and retain slot on failed reap. Evidence is currently only a nonempty string, not a verified readiness record. | FR3–FR6, FR11, TR3 |
| `worker_runtime/protocol.py`, `query_worker*`, `build_query_worker()` | Strict bounded request parsing, worker SQL reinspection, canonical success/error output exist. Add parent response decoding and compatible nonsecret limits. | FR3, FR6–FR8, TR4 |
| `local_cache/modeled.py` | `VerifiedModeledCache` downloads selected modeled objects, verifies manifest/projection/digests, pins and evicts. Add request mount staging and explicit startup/close integration. | FR1–FR2, FR12 |
| `query_results/previews.py` | Reuse `BoundedPreviewSequences`, signed cursors, original filters/generation, expiry and active leases. Integrate autonomous preview cleanup. | FR7, FR10, FR12 |
| `query_results/store.py`, `cleanup.py` | Reuse exact canonical spools, bounded indexes, reservations, reader leases, private owner lock and explicit cleanup. | FR8–FR10, FR12, TR4 |
| `application/services/{queries,preview}.py`, execution/input ports | Keep authorization before access, one SQL execution and current-role paging. Add narrow supervisor recovery ownership handoff for unresolved execution/pins. | FR1, FR4–FR5, FR7–FR8 |
| `bootstrap.py`, settings and HTTP startup | Construct inert resources, inject `DataHttpResources`, explicitly start/close in serving supervisor; no refresh ownership. | FR9–FR11, TR1, TR5 |

Paths above are relative to `src/outage_explorer/`. Existing tests demonstrate
controlled behavior, not actual Docker isolation. Worker engine limits are
currently hardcoded at 128 MiB memory, 16 MiB temporary space, 30-second
preparation, 40-second overall and 1-MiB output. The Docker example uses 512 MiB,
one CPU and 32 processes. These remain smoke candidates. Cache construction
currently creates an empty private directory; therefore defer actual cache
construction to supervisor `start`, behind inert forwarding ports. (TR5–TR6)

## Data model changes

No operational schema, publication or public response change. Add bounded
private analytical ownership records: process-instance identity, execution ID,
container identity/name, stage, exact staging directory, leased input handles,
creation/deadline state and recovery disposition. Records contain no SQL,
credentials, session identifiers, output cells or raw manifest contents.
Use a private bounded local recovery ledger plus process-liveness lock for
orphan reconciliation; it is lifecycle metadata, never durable query-ID state.
Record intended deterministic container identity before creation so a lost
create response remains discoverable. Persist before operations whose ambiguous
completion could strand a worker. (FR4–FR5, FR9–FR12, TR4)

## Interfaces & contracts

### Authorized input preparation and immutable mounts

1. Application authorization and SQL inspection remain before execution/input
   access. Reserve the analytical slot before any download; reference-free SQL
   still authorizes and uses no mounts. Select one publication and reuse its
   exact dataset projections. (FR1–FR2)
2. Keep cache pins acquired by the existing use cases. Runtime staging accepts
   only application-approved descriptors, checks bounded file count/bytes and
   copies them to a fresh private execution directory. Open through trusted
   directory descriptors, reject symlinks/nonregular files and verify digest,
   size and row identity while streaming. Verify the completed copy against the
   descriptor; never trust a path check followed by an unrelated reopen.
   Avoid hardlinks to mutable cache inodes. (FR2, TR2–TR3)
3. Install read-only digest-named staging files atomically; private parent
   ownership prevents untrusted host modification. Use staged mode 0444 for container UID 65534 with a host-owned 0700
   parent; exact file binds permit reads without exposing the parent or siblings. Bind each exact regular file read-only at `/inputs/<sha256>.parquet`
   using Docker structured mount options, never the whole cache. Fail on absent
   sources (do not use mount syntax that creates directories), duplicate identity
   conflicts, mount count/command-length exhaustion or unsupported host mapping.
   Worker already rechecks files and public schemas. (FR2, TR2)
4. Stage bytes have their own quota in addition to cache, spool and refresh
   allocations. S3 remains in the trusted host adapter (`S3ArtifactStore` supplies
   `reference/read`); worker receives no S3 capability. Pin expiry/eviction must
   not remove active staging or source leases. (FR2, FR12, TR2)
5. Normal order: worker death confirmed, container removal reconciled, execution
   staging removed, runtime reservation released, then application leases/pins
   released. Preview snapshot pins remain until its fixed expiry and final active
   lease; SQL input pins end after confirmed death, before result completion.
   Failed cleanup retains affected ownership and retries under supervision.
   (FR4–FR5, FR7–FR8, FR12)

### Docker lifecycle and control boundary

Use a dedicated bounded host Docker-control adapter with argument arrays and an
explicit local daemon selection; no shell interpolation, image pull, user-chosen
image/mount/env/options or remote daemon inference. Pin an already-built image
identity. Create first, then attach/start with stdin/stdout; disable TTY and
Docker log persistence for request/response streams. Drain stdout and stderr
concurrently with independent byte caps; retain only safe counters/codes, never
log payloads or raw stderr. Bound stdin writes, every control call and polling.
(FR3–FR6, TR2–TR3)

States: reserved → preparing → creation intended → created → running → stopping
→ death confirmed → removed → released. Any ambiguous create/start/wait/kill/
remove response enters recovery. Never infer death from Docker CLI exit, socket
closure, EOF or API request return. Inspect/wait for the specific immutable
container ID; confirm no running/restarting worker, reap host control subprocesses
and remove the container. Docker kill targets the complete container process
namespace; prove no surviving child in the real harness. Process death and
successful removal are distinct facts. Lost daemon connectivity retains the
slot/staging/pins until reconciliation. (FR4–FR5, FR9)

Honor the passed monotonic deadline: execution includes engine/result production
and bounded transport, capped by overall admission deadline. Reserve overall
headroom for stop/wait/remove; do not grant a fresh full timeout to each call.
At cancellation or either deadline, abort writes/read work, kill then wait/inspect
and remove under bounded control attempts. A cleanup deadline failure produces
unresolved ownership, not resource release. Supervisor close stops admission,
cancels work, joins controller threads and reconciles owned containers; repeated
close may retry unfinished cleanup. (FR4–FR6, FR9, TR3, TR5)

Existing `finally` blocks intentionally skip later pin release when reaping
raises, but do not register retained handles with a supervisor. Add an
application-owned execution lease/recovery port that explicitly transfers
execution reservation, SQL input pins/result reservation or preview active lease
before propagation. Supervisor keeps strong ownership until confirmed death;
no garbage-collection cleanup assumption. Test repeated failures/retries and
preview expiry while this lease remains active. (FR5, FR12)

### Isolation and configuration

Review a typed nonsecret runtime profile: immutable image ID, explicit Docker
endpoint, UID/GID, CPU quota, process cap, hard container memory and equal swap
ceiling, lower engine memory, bounded temporary storage, input/staging/cache/
result/encoding/transport bounds, preparation/execution/overall/control deadlines,
cleanup interval, private roots and allowed serving-process count. Require
`--network none`, read-only root, `--cap-drop ALL`, no-new-privileges and private
bounded `/tmp` with noexec/nosuid/nodev. No privilege, host namespaces, devices,
extra mounts or inherited worker environment. Explicit image baseline environment
is minimal; host Docker client environment is separately minimized. (TR2–TR3)

The existing tmpfs example is bounded private **memory-backed** temporary space;
charge it against total container/host memory. ADR-0007 expects bounded disk-backed
spill: implement a separately quota-enforced private disk-backed volume when
spill is enabled and prove the quota; otherwise mark tmpfs profile smoke-only and
leave spill readiness open. A bind directory or DuckDB setting alone is not a
hard storage quota. Docker Desktop path/UID behavior and supported Linux host
storage need evidence. (TR2, TR6)

Replace hardcoded worker bounds with an allowlisted, bounded nonsecret startup
profile, or require exact matching with the existing image profile and reject
any difference. Parent budgets cannot advertise configurable enforcement while
the image silently retains different values. Keep v1 public and internal request
contracts unchanged unless a separately reviewed protocol revision is needed.
Ten seconds and public result caps remain accepted ceilings. (FR3, TR3–TR4)

### Strict parent response decoding

Reject invalid UTF-8, trailing documents, duplicate keys, nonfinite JSON literals,
unknown/boolean version, wrong operation, extra properties, invalid shapes,
bounded recursion/item/schema expansion and inconsistent exit-status/error pairs.
Success has exact `version/operation/result`; safe error has exact `version/error`
with allowlisted code. A worker `invalid_request` after trusted request creation
is a runtime protocol fault, not necessarily a public user mistake. (FR3, FR6)

- Preview: require descriptors exactly matching `PreviewEncoding.columns` for
  the requested dataset, bounded row width/count and non-nullability. Validate
  canonical cells using shared type/encoding rules; reconstruct `date` and
  `Decimal` values needed by existing re-encoding, and require exact round-trip
  equality. Validate one key per row, dataset key width, date/identifier strings,
  key equality with row values, strict binary key order, original filters and
  `after` position. Require real bool `has_more`; no empty page with more.
  Keep cursor/signature/snapshot metadata in the application. (FR7, TR4)
- Query: validate every descriptor (indices, logical type/encoding, precision/
  scale, nested children and nullable/unit fields), recursive canonical cell,
  row width, real integer counts, truncation agreement and exact fixed limits.
  Reuse canonical JSON with the established field insertion order and demand
  exact canonical byte representation of the inner result. Reject noncanonical
  representations rather than normalize them. `QueryOutput.document` must equal
  what the worker's canonical encoder emitted, without HTTP envelope/version
  mixing. `store._verify_output` still provides independent structural/byte/index
  verification; it currently does not validate all descriptors/cells. Preserve
  encoded query date/decimal strings and duplicate labels unchanged. (FR8, TR4)

Map allowlisted SQL rejection via existing SQL errors, resource exhaustion to
`AnalyticalResourceError`, missing/corrupt inputs to `DataUnavailableError`,
query deadline to `AnalyticalTimeoutError`, daemon/start/protocol/crash/internal
failure to `RuntimeUnavailableError`; preserve current preview deadline mapping
and HTTP matrix. Unknown errors fail unavailable. Busy admission remains
`AnalyticalBusyError`; cancellation must clean ownership before translating
through the existing safe transport. (FR6, FR11)

### Supervisor, API lifecycle and readiness

An inert builder returns unstarted forwarding ports and `DataHttpResources`.
The dedicated serving-process supervisor explicitly `start`s them after process
ownership is known: validate profile/evidence, acquire owner lock, reconcile
creation-intended/owned containers, prepare private roots/cache and result store,
start autonomous preview/result/recovery cleanup, then accept analytical work.
Start failure rolls back only this instance's resources and keeps execution
unavailable. Never instantiate `VerifiedModeledCache` inside import/app construction.
Reconcile only bounded known owner labels/ledger, not arbitrary Docker containers.
Do not delete directories of live owners. (FR9–FR12, TR5)

Use existing `outage_data_start`/resource-close extension hooks from
`build_http_app(data_resources=...)`; the supervisor invokes start explicitly.
HTTP close never closes the independent refresh worker. Restart loses memory
query/cursor metadata, uses a fresh cursor key, returns existing unavailable
errors for old IDs and cold-loads new published inputs on demand. Kill/remove
proven-dead owner's analytical containers before reclaiming staging; retain
quarantine and fail admission if Docker cannot establish death. Published
S3, PostgreSQL and healthy refresh ownership remain untouched. (FR10–FR12)

The current result adapter enforces one serving process. Explicitly reject
multi-process/reloader/forked configurations for the proposed local supervisor;
this is an adapter constraint, **not** an accepted general WSGI mandate. A changed
shared ownership topology requires review before enabling another process.
(FR9, TR3–TR5)

Readiness requires a bounded nonsecret record covering exact image ID, protocol/
engine versions, runtime host/daemon/filesystem profile, every enforced budget,
controlled and real test evidence, measurements and user review/date. Validate
profile match and state in start, not just nonempty `evidence`. Material image,
config, platform or isolation changes invalidate matching evidence. Evidence
completion allows a later explicit enablement action; this planning work does
not authorize it. (FR11, TR6)

## Implementation phases

1. Freeze profile/transport and controlled decoder fixtures; expose startup limit
   mismatch and lifecycle invariants. (FR3, FR6–FR8, TR3–TR4)
2. Implement immutable staging, Docker lifecycle and recovery leases with
   controlled failure injection; no product enablement. (FR1–FR6, FR12, TR2–TR3)
3. Compose inert resources and explicit local supervisor/cleanup/restart handling;
   exercise existing API contracts with controlled adapters. (FR7–FR12, TR1, TR5)
4. Deliver the runnable real-runtime harness and user-owned T1.7 checklist;
   collect/review evidence only on explicit user direction. (TR6, AC7)
5. After readiness and separate enablement authorization, validate existing live
   preview/SQL/paging and rollback. (FR11, AC6–AC7)

## Dependencies & integrations

Local accessible Docker Linux container runtime and supported quota storage;
already-built application image; existing S3 publication read adapter and
PostgreSQL role/publication access in the trusted API process. Local work requires
no EC2 provisioning. No new Docker dependency is selected without version/bounded
control review. Credentials follow existing host configuration and never appear
in worker messages, profiles or evidence. (TR1–TR2, TR6)

## Risks & tradeoffs

- Daemon ambiguity/orphan containers: bounded ownership ledger and fail-closed
  reconciliation; unavailable capacity is safer than releasing live inputs.
- Staging copies cost disk/time: budget/measure separately; avoid mutable hardlink
  races and whole-cache mounts.
- Docker Desktop differs from Linux/EC2: evidence is platform-scoped; local
  readiness does not establish deployed budgets.
- API parser currently runs in-process: existing byte/AST caps do not prove a
  parser wall-clock bound. Track parser deadline isolation as a readiness risk;
  bounded Docker execution does not fix pre-launch parser CPU exhaustion.

### Alternatives considered

Direct S3 worker scans, worker HTTP service, API DuckDB and refresh SQL execution
conflict with accepted trust boundaries; do not introduce them. Whole-cache
mounts and output normalization conflict with authorized immutable inputs and
exact retained documents.

## Test strategy

- AC1–AC3: controlled descriptor/protocol corruption, canonical round trips,
  application denial before cache access, mount race failures and existing
  contract/encoding suites; real filesystem denial remains AC2 user-owned.
- AC4–AC5: fake Docker control with ambiguous create/start, blocked streams,
  timeout/crash/cancel, kill/wait/remove outages, retained leases through expiry,
  startup rollback/fork/repeated close and orphan reconciliation.
- AC6: existing preview/query lifecycle/HTTP tests with injected composition,
  old snapshot during new publication, busy admission, fixed expiry and zero new
  launches on retained GET paging.
- AC2, AC4, AC7: separate explicit real Docker harness with synthetic inputs,
  canary secrets (never real secrets), descendant termination, denial and hard
  quota probes; cold/warm representative input and refresh/API overlap measures.
  No controlled test substitutes for these checks.

## Assumptions

Planning can proceed before measured settings and deployment selection. Existing
cache/result/cursor behavior is reusable but supervisor-safe construction and
ownership handoff still require work. No accepted boundary changes are proposed.

## Open decisions

- Supported local Docker platform/daemon and mount path/UID semantics; immutable
  staging and enforced disk-spill quota backend. Resolve before real-runtime gate.
- Measured memory/CPU/process/temp/staging/cache/retention/encoding/transport and
  preparation/overall/cleanup bounds; three results per user/ten global remain
  proposals. Resolve from representative cold/warm and overlap evidence.
- Final API process/supervisor topology and private recovery-ledger storage; local
  single-owner profile is proposed and must be explicitly enforced/reviewed.
- Evidence record schema/reviewer/profile invalidation and parser wall-clock
  enforcement. Define and test before readiness; no guessed production values.
