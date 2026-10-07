# Phase 1: 3-file local candidate generation & transient quality
- Plan phase 1; prerequisites: resolved gates G1/G2. No runtime activation. T1.C precedes phase 2.
- Authorized sequencing: implement and test the new local pipeline via explicit
  injection; shared CLI/refresh/bootstrap cutover and removal of existing graph
  declarations/serialization move to T4.2/T4.3. Each new candidate writes exactly
  three resource files. Existing composed paths retain their regression coverage
  until switched; the new pipeline never converts or falls back to old layouts.
- Cohesive sibling modules/test files may isolate the new implementation in the
  listed layers, sharing existing codec/policies rather than duplicating them.
- [x] **T1.1** Update resource identities and candidate/request/report/receipt port contracts in `src/outage_explorer/application/ports/artifacts.py`, `src/outage_explorer/application/ports/candidates.py`, `src/outage_explorer/application/ports/connector.py`, `src/outage_explorer/application/dto.py` to carry exactly three grain references, base identity, interval, versions and bounded in-memory quality; define the new pipeline without graph dependencies; retain declarations required by existing consumers until phase 4, without claiming proposed APIs already exist. Preserve unrelated offline verification DTOs and explicit local retry identity. Depends on G1/G2. (FR1, FR2, FR4, FR6, FR7; TR1, TR2, TR4; AC1, AC3, AC5)
- [x] **T1.2** Update unified resource schema/round-trip codecs in `src/outage_explorer/infrastructure/parquet/schemas.py` and only the necessary baseline row representation in `src/outage_explorer/domain/refresh.py`; retain pure selection policies, exact decimals, natural keys and approved retention fidelity, with public columns unchanged in `src/outage_explorer/domain/datasets.py`. Resolve G2 first; do not fabricate source strings/origins or silently treat representation errors as exclusions. Depends on T1.1. (FR1, FR6; TR2, TR4; AC2, AC3)
- [x] **T1.3** [P] Update bounded single-resource write/verify dispatch in `src/outage_explorer/infrastructure/parquet/storage.py` to emit one unpartitioned file per grain, with exact hashes/bytes/rows and existing aggregate staging limits; eliminate duplicate public/model output, not bounds. Depends on T1.2; independent of T1.4. (FR1, FR8; TR1, TR2; AC1, AC2)
- [x] **T1.4** [P] Update `src/outage_explorer/infrastructure/parquet/evidence.py` and the write seam in `src/outage_explorer/infrastructure/parquet/connector.py` to validate sanitized pages/source order and collect bounded transient input/quality without raw batch, page or transport serialization; preserve failed-page handling and repository anomaly fixtures. Depends on T1.2; independent of T1.3. (FR2, FR7; TR4; AC1, AC5)
- [x] **T1.5** Update staging/day-walk/`prior_days`/merge decoding in `src/outage_explorer/infrastructure/parquet/partitions.py` to consume T1.4 transient input and stream T1.3 unified prior files in sorted date/key groups; reject duplicate/unsorted/over-budget inputs and preserve invalid, absent, outside-interval and wholly excluded retention without persisted ledgers. Depends on T1.3/T1.4. (FR2, FR6, FR7; TR2; AC3, AC5)
- [x] **T1.6** Update build/transient semantic verification in `src/outage_explorer/infrastructure/parquet/candidates.py` without using candidate manifest serialization in `src/outage_explorer/infrastructure/parquet/manifests.py` (final retirement at phase 4); produce three verified references and bounded summaries, check row uniqueness/counts/values/coverage against local merge results, and stop disposition/ledger/manifest writes. Verification must precede release of transient inputs. Depends on T1.5. (FR1, FR2, FR6, FR7, FR8; TR1, TR2, TR4; AC1, AC3, AC5)
- [x] **T1.7** Update local candidate coordination/report adaptation in `src/outage_explorer/application/services/connector.py`, `src/outage_explorer/infrastructure/parquet/connector.py`, `src/outage_explorer/infrastructure/connector_report.py` to consume T1.1/T1.6 results and exact baseline inputs through explicit new-pipeline injection instead of reopening/replaying graph ancestry (shared entrypoint wiring switches at phase 4); keep bounded progress, report failure and candidate-only semantics. Depends on T1.6. (FR1, FR2, FR6, FR7; TR1, TR4; AC1, AC3, AC5)
- [x] **T1.8** Update local tests in `tests/integration/test_single_file_datasets.py`, `tests/integration/test_connector_parquet.py`, `tests/integration/test_connector_reruns.py`, `tests/integration/test_connector_evidence.py`, `tests/integration/test_candidate_verification_progress.py`, `tests/unit/test_connector_service.py`, `tests/unit/test_refresh.py` for exactly three outputs, round-trip exactness, last-valid/identical duplicates, transient validation/reason conservation, retention and failure bounds; preserve meaningful anomaly/negative fixtures, add equivalent new-pipeline assertions and retain existing composed-path regression tests until phase 4; do not discard behavioral coverage. Depends on T1.7. (FR1, FR2, FR6, FR7, FR8; TR1, TR2, TR4; AC1, AC2, AC3, AC5)
- [x] **T1.C** Checkpoint: inspect `docs/specs/refresh-persistence/tasks/phase-1.md` against `docs/specs/refresh-persistence/spec.md`; verify local AC1/AC2/AC3/AC5 obligations through T1.8 tests, through explicit new-pipeline injection, with current composed consumers regression-tested; S3/PG/worker integration and shared entrypoint cutover remain later-phase acceptance. Run README/`Makefile` commands `.venv/bin/python -m ruff check .`, `.venv/bin/python -m ruff format --check .`, `.venv/bin/python -m mypy`, `.venv/bin/python -m pytest -m 'not live_provider'` (includes `tests/architecture/test_import_boundaries.py`); record actual failures/missing disposable test prerequisites and block advancement on unresolved contracts or regressions. No tests run for task-document creation. (FR1, FR2, FR6, FR7; TR1, TR2, TR4; AC1, AC2, AC3, AC5)

## Historical sequencing finding and resolution — October 6, 2026

G1/G2 were explicitly resolved by the user: accept ADR-0060 and preserve the
existing private provenance, original numeric strings and exact calculation
evidence in the unified resource schema; analytical views retain their explicit
public projection. The remaining blocker is phase sequencing, not those decisions.

T1.1/T1.6/T1.7 replace the shared graph contracts and stop manifest writes, while
the same concrete candidate composition remains connected to these later-phase
consumers:

- `application/services/connector_artifacts.py`: `PersistConnectorArtifacts.execute`
  requires `ConnectorGraph.graph()` and a final manifest object;
  `CreateDurableConnectorCandidate.execute` requires `ConnectorReport.manifest`.
- `application/services/refresh_execution.py`: `RefreshExecution.execute` requires
  the report manifest, graph replay, `CandidateManifest` reopening and exact
  `base_manifest_object` checks before persistence/publication.
- `application/ports/refresh_execution.py`: `RefreshConnector` still declares
  graph, manifest restore/reopen and manifest-based persistence ports.
- `bootstrap.py`: `execute_connector`, `execute_connector_artifacts` and
  `build_refresh_worker` inject the affected builder/evidence adapters; local
  prior input is still parsed as a single manifest `StoredObject`.

Switching those shared producers in phase 1 leaves the above public paths unable
to consume the result until phases 2–4. Keeping a second graph-writing producer
would contradict T1.6; accepting those regressions would contradict T1.C and the
manifest's rule that incomplete downstream integration is not phase acceptance.
An updated plan must adapt the consumers before switching the shared producers,
and sequence that cutover into a verifiable boundary before implementation resumes.
No source/test changes or
task completions remain from this investigation; no phase checks were run.

The user subsequently directed proceeding after the local-build/shared-cutover
separation was explained. The plan/manifest now record that correction: Phase 1
completes the new local implementation and meaningful checks without changing
shared composition; phases 2–3 prepare consumers, and phase 4 switches/removes the
old composition. The finding above explains the correction rather than remaining
a blocker. This changes sequencing, not the accepted three-file contract or ACs.


## Phase 1 implementation evidence

T1.1–T1.8 are implemented through explicit new-pipeline injection. The new
`CreateResourceCandidate` / `ParquetResourceBuilder` path collects bounded
transient input, semantically compares its three resource files against the
pure merge, and returns exact references plus aggregate quality. Existing
CLI/refresh/bootstrap composition remains scheduled for the phase-4 switch.
No new candidate writes supporting artifacts or a manifest; no old-format
conversion or graph fallback was added.

`tests/integration/test_resource_candidates.py` adds equivalent new-pipeline
coverage while the existing composed-path tests retain their prior regression
coverage. It verifies exactly three local Parquet outputs, original numeric
strings/provenance/exact calculations, September fixture parity, duplicate and
exclusion-reason accounting, invalid/absent/outside/whole-route retention,
malformed baselines, source/storage failures, shared bounds and 30/183-day walks.
Its bounded isolated DuckDB test verifies public-only `SELECT *` columns and
private-column rejection for `national`, `facilities` and `generators`.
Pure service tests additionally enforce prior-before-source ordering, source
input grain/interval matching before modeling, and safe failure/report behavior.
Fresh-session tests prove all three exact baseline/readback files are charged
idempotently to the shared byte/object budget, without directory listing or
double charging; future file writes and transient inputs share that budget.

Actual checks completed:

- Ruff lint: passed.
- Ruff format check: passed (407 files).
- mypy: passed (145 source files).
- Focused resource/service tests: 72 passed (final combined focused/architecture run: 194 passed).
- Architecture tests: 122 passed.

T1.C passed on the final frozen snapshot: the complete
`.venv/bin/python -m pytest -m 'not live_provider'` suite collected 2,048 tests
and finished with **2,009 passed, 39 skipped in 548.61 seconds**, exit 0. The
main agent supplied explicit disposable loopback PostgreSQL and installed
Chromium prerequisites; the run log is
`/private/tmp/outage-refresh-phase1-full.log`. The 39 skipped checks remain unperformed evidence; this local suite does not
claim live-provider or production-runtime acceptance.
The initial sandbox attempt was interrupted after confirming loopback database
connections were blocked by sandbox permissions; it was superseded by the
successful authorized final run.

Local AC1/AC2/AC3/AC5 obligations are verified through explicit new-pipeline
injection: exactly three local files and no supporting serialization, public
projections in bounded subprocess SQL, faithful sequential retention and
conserved aggregate quality. Existing composed paths passed their regression
coverage. S3 persistence/readback, PostgreSQL descriptor/quality publication,
production worker/cache integration and shared entrypoint cutover remain phase
2–4 acceptance; no full-spec AC is marked complete by local evidence alone.


Implementation file mapping:

- `application/ports/artifacts.py`, `application/ports/candidates.py`,
  `application/ports/connector.py`, `application/dto.py`: unified resource kind,
  transient input, exact baseline/candidate/request/report/receipt contracts.
- `domain/refresh.py`, `infrastructure/parquet/schemas.py`: expose existing pure
  baseline validation and reuse the exact physical codec for resource files.
- `infrastructure/parquet/storage.py`: bounded single-file resource dispatch,
  statistics, exact existing-file adoption and shared conservative transient/file
  staging accounting.
- `infrastructure/parquet/evidence.py`, `infrastructure/parquet/connector.py`:
  transient page/transport validation and explicitly injectable resource seams.
- `infrastructure/parquet/partitions.py`,
  `infrastructure/parquet/candidates.py`: sorted exact resource baseline streaming,
  transient day grouping, pure merge and pre-release semantic comparison.
- `application/services/connector.py`, `infrastructure/connector_report.py`:
  independent candidate coordination and bounded metadata-only local reports.
- `tests/integration/test_resource_candidates.py`,
  `tests/unit/test_connector_service.py`: equivalent new-pipeline behavior,
  negative boundaries and real Parquet/isolated DuckDB coverage.
