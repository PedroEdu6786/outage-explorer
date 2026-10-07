# Refresh persistence optimization — Proposals

## Proposal A — Existing workers, narrow replay cut (author: rafachafa, Pragmatist)
- **Approach:** Wire the existing bounded scheduler into HTTP dependency uploads
  and final fresh recovery downloads. Use whole-object tasks and replenishment
  on completion; keep discovery, graph accounting, root transfer, and semantic
  replay coordinated. Match SDK connection pool size to the admitted count.
- **Configuration:** Add operational `OUTAGE_REFRESH_PERSISTENCE_WORKERS`, strictly
  1–3, initially 3 for newly admitted HTTP runs. Persist `persistence_workers` in
  the existing immutable configuration JSON. Previously admitted snapshots without
  the field use 1; invalid present values fail. CLI defaults stay unchanged.
- **Resource admission:** Reuse existing CLI logical admission equations:
  `n(2F+R) <= M`, `2G+nF <= T`, plus `nF <= upload_spool`. Current defaults:
  F=32,000,000; R=1,000,000; G=256,000,000; M=512,000,000; T=700,000,000;
  upload spool=100,000,000 bytes. For n=3: 195,000,000, 608,000,000, and
  96,000,000 respectively. These calculations are not host resource measurements.
  Validate before source work; keep locked, shared S3 request/byte/spool counters.
- **Lifecycle:** Candidate and persistence have separate stage deadlines.
  Persistence begins a fresh deadline covering local graph verification through
  fresh remote replay. One event/deadline per stage is shared by local checks,
  scheduler, and S3; no reset per object, root, or readback. Replace indefinite
  completion waits with bounded polling, check ownership and stop admission on
  failure, then join before closing storage/SDK resources. Preserve SDK timeouts.
- **Replay cut:** Remove only the post-prior-restore `graph()` and tautological
  root-last check in refresh execution. `restore()` already validates exact
  references, conflicts, graph bounds, ancestry and full replay. Retain this call
  if adversarial tests identify a distinct check. Keep candidate identity checks,
  persistence's local graph verification, and independent fresh remote replay.
- **Phase outline:** configuration/resource admission; both-direction concurrency
  and lifecycle checks; narrow replay elimination and scheduling documentation.
- **Data-model changes:** additive configuration JSON field; no migration/backfill
  or changes to durable manifests/receipts/HTTP schemas.
- **Explicitly cut:** baseline study, progress API, CPU pools, new services,
  verification caches, compaction, or weaker integrity checks.
- **Author-admitted risks:** SDK calls delay cooperative cleanup; 3 workers raise
  instantaneous usage; old executables reject unknown configuration fields, so
  compatible readers/workers must precede new admissions. Speedup remains unknown.
- **Traces to:** FR1–FR7, TR1–TR5, AC1–AC6.

## Proposal B — Phase-scoped verified graph (author: gamachiel, Architect)
- **Approach:** Same existing object scheduler, both transfer directions, root and
  replay barriers, and SDK pool alignment; add scoped verification reuse.
- **Configuration:** New admissions explicitly capture 3; strict supported range
  1–3. Missing historical field means 1, invalid present values fail. Preserve
  existing positional constructors and CLI defaults; authorization and idempotent
  lookup precede new admission. Add only configuration JSON, never backfill history.
- **Resource admission:** Share a small pure validator for the same equations and
  allowances as A. Preserve 100,000 requests and 1,600,000,000 logical wire bytes
  including retries/readback; one locked S3 session per persistence stage. Disable
  SDK-internal retries as today and match pool size to the admitted worker count.
- **Lifecycle:** Same phase-specific absolute deadlines and shared cancellation
  as A. Ownership loss invalidates work; timed scheduler waits and root/receipt
  boundaries check it. Join all work before response/store/client cleanup. Never
  inherit an expired candidate deadline into persistence or reset time on readback.
- **Scoped reuse:** Introduce an ephemeral verifier-owned graph result containing
  the verified manifest and exact closure, bound to store session, root, bounds,
  and verification contract. Refresh identity checks and persistence consume it.
  Recheck every referenced object's length/hash before reusing semantic conclusions;
  upload staging validates the digest again. No filename/timestamp trust or caller
  verified flag. Preserve ancestry, provenance, repeated-reference accounting and
  coverage checks. Remote verification always uses fresh independent staging;
  CLI's reference-based entry points keep full verification.
- **Phase outline:** frozen config/legacy decoding/resource admission; concurrent
  upload and download wiring/lifecycle; scoped verification reuse; documentation.
- **Data-model changes:** additive admitted configuration field, ephemeral graph
  result contract; no persisted graph-format or HTTP change.
- **Explicitly cut:** baseline study, progress API, CPU pools, storage changes.
- **Author-admitted risks:** cooperative shutdown waits for bounded I/O; unsafe
  proof reuse can miss mutation; remaining serial replay may dominate latency.
- **Traces to:** FR1–FR7, TR1–TR5, AC1–AC6.

## Outcome
- **Selected:** Revised A: freeze configuration, wire existing concurrency in both
  directions, enforce lifecycle/cleanup, document work distribution; then a
  separately gated narrow replay cut. See [plan](../plan.md).
- **Rejected/deferred:** B's broad semantic-proof reuse adds a verification
  contract and mutation/ancestry obligations. rafachafa, kings and estebanquito
  challenged its first-release value; gamachiel conceded and deferred it.
- **Shared revisions:** logical-resource claims corrected; task-owned streams,
  cooperative cleanup limitations, phase-specific evidence wiring, actual HTTP
  composition tests, tolerant history reads with fenced validation, and compatible
  rollback added. [Decisions](03-decisions.md) preserve arguments and concessions.
- No accepted architectural boundary changes. These are reviewed proposals, not
  implemented defaults or runtime acceptance.
