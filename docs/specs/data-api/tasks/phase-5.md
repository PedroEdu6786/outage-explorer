# Tasks: One-execution SQL and retained paging
> Status: complete; controlled checkpoint passed · Slug: data-api · Plan: ../plan.md · Spec: ../spec.md

## Phase 5 (plan phase 5)

- [x] **T5.1** Create retained-result and reservation contracts — `src/outage_explorer/application/ports/query_results.py`, `src/outage_explorer/domain/query_results.py`; bind owner/grains/generation/page size, completion-based fixed expiry, bounded offsets and canonical row/byte caps. (FR9–FR12, FR20, TR1, TR3–TR6)
- [x] **T5.2** Create bounded ephemeral metadata/private spool implementation — `src/outage_explorer/infrastructure/query_results/store.py`; reserve in-flight quotas/worst-case bytes, retain immutable output once, reject capacity without unexpired eviction and lease active readers. Depends on T5.1 and Phase 1 encoding. (FR9–FR12, TR3–TR6)
- [x] **T5.3** Create query execution/paging services — `src/outage_explorer/application/services/queries.py`; resolve identity, inspect references, authorize every grain before inputs, execute unchanged SQL once, complete retention before response and serve arbitrary/revisited pages without execution. Handle deliberate reference-free authorization and initial out-of-range owned-result recovery. Depends on T5.2 and Phase 4 execution/input seams. (FR1, FR3, FR7–FR10, FR12, FR20, TR1, TR3–TR7)
- [x] **T5.4** Create autonomous cleanup and process-owned lifecycle — `src/outage_explorer/infrastructure/query_results/cleanup.py`, `src/outage_explorer/bootstrap.py`; reclaim expired/dead-owner state without requests, preserve active readers/durable artifacts and reject incompatible ownership topology. Depends on T5.3. (FR10–FR11, TR5–TR6)
- [x] **T5.5** Create real-adapter query sequence/byte-boundary tests — `tests/integration/test_query_results.py`; cover duplicates, ordered/limited SQL, every page position, exactly/over 1,000 rows, UTF-8/nested/schema bytes, oversized first/later rows, size mismatch and no added clauses. Depends on T5.4. (FR7, FR9, FR12, TR3–TR4, TR7)
- [x] **T5.6** Create ownership/expiry/cleanup/contention tests — `tests/integration/test_query_lifecycle.py`; verify fresh roles, foreign/lost IDs, fixed completion expiry, reservations, concurrent readers/orphans and busy/timeout isolation. Depends on T5.4. (FR1, FR10–FR12, FR20, TR1, TR3, TR5–TR6)
- [x] **T5.C** Checkpoint: verify retained one-execution paging and bounded lifecycle — `tests/integration/test_query_results.py`, `tests/integration/test_query_lifecycle.py`, `tests/architecture/test_import_boundaries.py`, `docs/specs/data-api/tasks/phase-5.md`; run Ruff/mypy and require actual launcher evidence before runtime claims. Depends on T5.5–T5.6. (AC1, AC3, AC7–AC13, AC21, AC32–AC33)


## Checkpoint evidence

- T5.1–T5.6 implement result/reservation contracts, private immutable spools,
  completion-based fixed 15-minute expiry, bounded row offsets and page size,
  current role checks, original-owner paging and explicit lost/expired outcomes.
- Query services inspect unchanged SQL and authorize its complete reference set
  before preparation. Reference-free expressions have an explicit recognized-role
  operation; the original empty analytical-grain denial remains intact. Results
  finish materialization and reaping before retention or response. Later pages
  use retained offsets and never inspect, prepare inputs or execute SQL again.
- Worst-case byte/count reservations include in-flight requests. Capacity failure
  does not evict an unexpired result; failed admission releases its reservation.
  Input pins release after confirmed worker reaping. Uncertain reaping deliberately
  retains capacity and pins until supervision resolves liveness.
- Explicit bootstrap composition constructs inert store/cleanup resources;
  startup/shutdown controls the autonomous cleanup thread. This process-owned
  store rejects multiple serving processes and forked reuse; this compatibility
  restriction does not accept one WSGI process as the global deployment mandate.
  Reader leases preserve active reads at expiry. Advisory owner locks prove dead
  processes before reclaiming private orphans; unknown/durable files are preserved.
- Lifecycle checkpoint: approved disposable PostgreSQL tests passed 24 cases in
  70.35 seconds, covering fresh roles/logout, foreign IDs, fixed expiry, in-flight
  reservations, byte capacity, autonomous cleanup, concurrent readers, dead/live
  owners, topology, busy admission and controlled timeout recovery.
- Real-engine sequence/byte checkpoint: 18 tests passed in 33.13 seconds using
  approved disposable PostgreSQL, verified Parquet and controlled DuckDB
  subprocesses. Fixtures are synthetic and use existing accepted
  scalar/VALUES SQL. The UTF-8 fixture explicitly casts lists to VARCHAR because
  DuckDB's overloaded concat(list) returns a list and correctly hits nesting limits.
- Architecture, role-policy, existing canonical encoder and SQL-compatibility
  regression: 166 tests passed. Ruff lint/format and strict mypy (119 source files)
  passed. New exact reserved UTF-8/schema and malformed-output tests also passed.
- This verifies the controlled application/adapter portions of AC1, AC3,
  AC7–AC13, AC21, AC32 and AC33. Product HTTP/error transport is Phase 6.
  AC8/AC33 actual Linux denial, ten-second termination/tree reaping and measured
  resource/overlap claims remain gated by T1.7. No production launcher, live
  publication, deployment or cloud mutation was performed. Retention quotas and
  preparation/storage profiles remain explicit unreviewed test settings.
