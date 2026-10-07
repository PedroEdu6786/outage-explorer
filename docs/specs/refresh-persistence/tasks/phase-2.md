# Phase 2: 3-file S3 persistence & readback verification
- Plan phase 2; prerequisites: T1.C and G4. T2.C precedes phase 3.
- Under the authorized sequencing correction, prepare three-resource consumers
  through explicit injection and preserve existing composed paths until the
  phase-4 switch. No new resource candidate/persistence operation writes a graph;
  final removal of obsolete shared declarations/composition belongs to T4.2/T4.3.
- The staged resource consumers live in cohesive sibling modules
  `application/services/resource_artifacts.py` and `infrastructure/s3/resources.py`;
  the originally named shared modules retain their existing consumers until Phase 4.
  New controlled cases live in `tests/integration/test_resource_artifacts.py` and
  `tests/unit/test_connector_worker_cancellation.py`; the named existing suites
  remain regression coverage rather than being rewritten around a second layout.
- [x] **T2.1** Update typed S3 worker default to 3 while enforcing explicit 1–3 overrides and unchanged aggregate limits in `src/outage_explorer/settings.py`; preserve JSON/flag precedence and environment-only secrets. Depends on T1.C. (FR3; TR3; AC6)
- [x] **T2.2** [P] Update exact resource addressing in `src/outage_explorer/infrastructure/s3/artifacts.py` according to G4/T1.1; preserve single conditional PutObject, ChecksumSHA256, ContentLength plus complete streamed SHA-256 readback, bounded retries and locked aggregate requests/wire/staging counters across all three workers. Use known descriptor sizes, not manifest HEAD discovery; do not list/delete objects or add multipart upload. Depends on T2.1/G4; independent of T2.3. (FR1, FR3, FR4, FR8; TR1, TR3; AC1, AC6)
- [x] **T2.3** [P] Update `src/outage_explorer/infrastructure/connector_workers.py` cancellation/deadline polling and task-owned stream completion to stop admission and join all workers before shared cleanup; preserve ordered results and cooperative rather than claimed hard termination. Depends on T2.1; independent of T2.2. (FR3, FR8; TR3; AC6)
- [x] **T2.4** Update three-reference persistence coordination in `src/outage_explorer/application/services/connector_artifacts.py` to validate T1.6 candidate identities, transfer/readback only the three resource files and return their exact verified receipt after every task completes; remove dependency graph/manifest upload and redundant replay reads, abort without publication on any failure/cancellation. Depends on T2.2/T2.3. (FR1, FR3, FR4, FR8; TR1, TR3, TR4; AC1, AC6)
- [x] **T2.5** Update exact-three-file explicit recovery in `src/outage_explorer/infrastructure/parquet/connector.py` and `RecoverConnectorArtifacts` in `src/outage_explorer/application/services/connector_artifacts.py` to restore supplied descriptors and check bytes/schema/rows without EIA or ancestor evidence; clean owned transient readback files after join, preserve explicit CLI retry artifacts and historical S3 objects. Depends on T2.4 and T1.2/T1.5. (FR4, FR6, FR8; TR1, TR2, TR4; AC3, AC6)
- [x] **T2.6** Update `tests/integration/test_s3_artifacts.py`, `tests/integration/test_connector_artifacts.py`, `tests/integration/test_connector_concurrency.py`, `tests/unit/test_connector_settings.py`, `tests/unit/test_connector_durability.py` with controlled SDK/barrier tests for worker counts 1/2/3, exact three PUT targets and successful readbacks, 412 identity conflicts, corruption/short bytes, retries, aggregate cap exhaustion, cancellation and join-before-cleanup. Assert behavior/object sets, not estimated latency/storage or hard I/O termination. Depends on T2.5. (FR1, FR3, FR4, FR6, FR8; TR1, TR3; AC1, AC3, AC6)
- [x] **T2.C** Checkpoint: inspect `docs/specs/refresh-persistence/tasks/phase-2.md` against `docs/specs/refresh-persistence/spec.md`; verify AC1 exact durable object set, AC3 exact baseline restore and AC6 readback/concurrency/cleanup via T2.6 controlled tests, with pointer/lease guarantees still due in phases 3–4. Run README/`Makefile` commands `.venv/bin/python -m ruff check .`, `.venv/bin/python -m ruff format --check .`, `.venv/bin/python -m mypy`, `.venv/bin/python -m pytest -m 'not live_provider'` (including architecture tests); report actual results/missing disposable prerequisites and block on regressions. No AWS/source calls or tests for task-document creation. (FR1, FR3, FR4, FR6, FR8; TR1, TR3, TR4; AC1, AC3, AC6)


## Implementation and checkpoint evidence

- T2.1: `settings.py` adds `ResourceWorkerSettings` and
  `resource_worker_settings` with three S3 workers by default; explicit 1–3
  overrides, JSON/flag precedence and existing aggregate limits remain checked.
  Existing composed consumers retain their previous settings until phase 4.
- T2.2: `infrastructure/s3/resources.py` implements the ADR-0061 exact physical
  addresses, descriptor preflight and resource-only transfer receipt. Shared
  conditional PUT, complete GET, retries and locked bounds stay in
  `infrastructure/s3/artifacts.py`; no HEAD/list/delete/multipart discovery exists
  on the new resource consumer.
- T2.3: `infrastructure/connector_workers.py` polls cancellation/deadline between
  admissions and bounded waits; task streams close in `finally`, and every
  admitted worker joins before recovery cleanup. This remains cooperative I/O.
- T2.4: approved sibling `application/services/resource_artifacts.py` provides
  `PersistResourceArtifacts`, explicitly injected with the resource ports in
  `application/ports/connector.py`. It verifies local files, transfers exactly
  three targets, obtains one complete readback per successful conditional PUT,
  and returns the exact descriptors plus admitted generation/base/interval/version
  identity only after all tasks finish. It confers no publication authority.
- T2.5: `RecoverResourceArtifacts` and
  `infrastructure/parquet/connector.py::restore_resources` restore exact supplied
  files without source or ancestor discovery. The shared recovery disk reservation
  covers all missing files through verification or cleanup. Expected byte identity
  is checked before local commit in `parquet/storage.py`; failure cleanup removes
  only tracked recovery-owned files after join and still works after cancellation.
  Existing caller files survive. Bytes, physical schema, row counts and modeled
  baseline policies are verified before success.
- T2.6: approved sibling `tests/integration/test_resource_artifacts.py` covers
  counts 1/2/3, actual 2/3-worker PUT/GET overlap, the exact three-object/six-call
  successful persistence set, admitted identity and cross-generation recovery,
  unsafe addresses, conditional conflicts/retries, byte corruption/short reads,
  byte-valid schema/row mismatch, faulty transfer-port output, shared caps,
  recovery aggregate reservation and joined cancellation cleanup. Dedicated
  `tests/unit/test_connector_worker_cancellation.py` verifies admission/deadline
  polling and joining; settings tests cover new defaults and overrides. The
  existing resource candidate receipt fixture uses the refined exact identity.
- Final static checks passed: `.venv/bin/python -m ruff check .`,
  `.venv/bin/python -m ruff format --check .` (412 files),
  `.venv/bin/python -m mypy` (147 source files).
- Expanded focused and architecture regression suite passed: **388 passed in
  37.47s** across resource candidates/artifacts, existing S3/artifact consumers,
  settings, worker cancellation and architecture tests. Controlled transports
  used no live AWS/EIA calls.
- T2.C passed on the frozen final source snapshot: complete
  `.venv/bin/python -m pytest -m 'not live_provider'` with disposable PostgreSQL
  and cached Chromium: **2,052 passed, 39 skipped in 486.67s**, exit 0. Architecture
  tests are included. AC1 exact durable set, AC3 exact baseline recovery and AC6
  readback/concurrency/joined cleanup are established for the explicitly injected
  path by controlled tests; publication pointer/lease guarantees remain due in
  phases 3–4, and shared production composition/removal remains due in phase 4.
