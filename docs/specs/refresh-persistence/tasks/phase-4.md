# Phase 4: Refresh execution orchestration & end-to-end verification
- Plan phase 4; prerequisites: T3.C and all manifest gates. Tests use controlled HTTP/S3, disposable PostgreSQL and isolated DuckDB, not live loading or deployment.
- [x] **T4.1** Update per-run connector port/orchestration in `src/outage_explorer/application/ports/refresh_execution.py`, `src/outage_explorer/application/services/refresh_execution.py` and bounded quality encoding in `src/outage_explorer/application/refresh_outcomes.py` to restore the admitted base's three descriptors, validate generation/base/interval/version/coverage and T2.4 receipt equality, publish T3.1 descriptors and exact transient summaries, and finish retained/failed outcomes without moving the prior pointer. Preserve fresh owner checks before I/O and publication-unknown reconciliation rather than overwriting uncertainty. Depends on T3.C and T1.6/T2.4/T2.5/T3.4. (FR1–FR8; TR1, TR2, TR4, TR5; AC1–AC6)
- [x] **T4.2** Switch shared concrete refresh/connector/analytical wiring in `src/outage_explorer/bootstrap.py` to supply the new ports, generation descriptors and T3.5 cache; use separate frozen candidate/persistence deadlines, configured 1–3 S3 workers/default 3, sufficient SDK connection pool, shared cancellation/aggregate preflight and lease checks, with workers joined before owned staging/transport cleanup. Remove obsolete shared graph/manifest candidate composition and serializers after every consumer switches; no dual graph-writing candidate path or old-layout conversion remains. Keep factories/imports inert and independent refresh supervision; logical budget admission is not measured RSS/filesystem containment. Depends on T4.1/T2.1/T2.3/T3.5. (FR1, FR3, FR4, FR5, FR6, FR8; TR1, TR3, TR5; AC1, AC2, AC3, AC4, AC6)
- [x] **T4.3** Update contributor durable/retry/recover transport adaptation in `src/outage_explorer/entrypoints/cli/connector.py`, `src/outage_explorer/settings.py`, `src/outage_explorer/application/services/connector_artifacts.py`, `src/outage_explorer/infrastructure/connector_report.py` to consume exact T1.1/T2.4 descriptors without an S3 manifest; preserve default durable success, explicit local-only, S3 validation before source, safe error reporting and explicit persistence retries with local resources preserved. Use only the approved G4 identity contract; do not create publication/reset capabilities or change product HTTP contracts. Depends on T4.2. (FR1, FR3, FR4, FR8; TR1, TR3, TR4; AC1, AC6)
- [x] **T4.4** Update guarded publication and composed regression suites in `tests/integration/test_refresh_publication_files.py`, `tests/integration/test_refresh_execution.py`, `tests/integration/test_refresh_recovery.py`, `tests/integration/test_connector_cli.py`, `tests/integration/test_data_api_http.py`, `tests/acceptance/test_data_api_lifecycle.py` to prove exactly three durable files/no supporting objects, exact PG keys/hash/bytes/rows and quality reasons, two sequential refreshes with invalid/absent/partial-all-excluded/outside-interval retention and valid replacement. Inject upload/readback/deadline/cancellation/bounds failures, lease loss and ambiguous commit; verify no displacement, join/cleanup and explicit Admin retry, including authorization before analytical/source I/O and API-only restart independence. Preserve Finding 001 fixtures and negative architecture coverage. Depends on T4.3. (FR1–FR8; TR1–TR5; AC1–AC6)
- [x] **T4.5** Extend controlled end-to-end reads in `tests/integration/test_refresh_execution.py`, `tests/integration/test_catalog_preview.py`, `tests/integration/test_query_results.py` to query and preview the newly published and retained-generation resource files through existing isolated boundaries using SQL names `national`, `facilities`, `generators`; assert public column order/types/precision, authorization and preserved pagination/pins. Exercise refresh→three-file readback→PG publication→DuckDB without cloud credentials; do not assert estimated operation/storage reductions as measured performance or certify host isolation from fixture workers. Depends on T4.4. (FR1, FR4, FR5, FR6, FR7, FR8; TR1, TR2, TR5; AC1–AC6)
- [x] **T4.C** Checkpoint: inspect `docs/specs/refresh-persistence/tasks/phase-4.md` and `docs/specs/refresh-persistence/tasks.md` against `docs/specs/refresh-persistence/spec.md`; verify all AC1–AC6 through T4.4/T4.5 with exact descriptor/quality assertions, bounded transfers, retention, fresh authorization and lease/transaction failures. Run README/`Makefile` commands `.venv/bin/python -m ruff check .`, `.venv/bin/python -m ruff format --check .`, `.venv/bin/python -m mypy`, `.venv/bin/python -m pytest -m 'not live_provider'` (includes `tests/architecture/test_import_boundaries.py`); with existing disposable PostgreSQL/Chromium prerequisites also run `make check`/`make test`, reporting actual results and remaining runtime evidence. Confirm gates and scoped changes; no deployment, historical object deletion, pointer reset or initial live load. No tests run for task-document creation. (FR1–FR8; TR1–TR5; AC1–AC6)


## Implementation and checkpoint evidence — October 6, 2026
- T4.1/T4.2: shared refresh restores only the base's three exact PostgreSQL descriptors,
  checks base/run/interval/version/coverage and full receipt equality, then publishes
  resource descriptors and bounded transient quality. Fresh owner/epoch/live-lease/base
  fences and publication-unknown reconciliation remain enforced. Separate frozen
  deadlines and `s3_workers` (1–3, default3) are persisted with admission configuration;
  lease-aware source/transfers share cancellation and aggregate preflight. Per-run
  staging is exclusively owned and removed only after admitted work joins.
- T4.2/T4.3: shared CLI/refresh/analytical composition now uses resource services,
  `PostgresqlResourcePublicationStore`, `VerifiedResourceCache` and strict unified-schema
  workers. Removed obsolete graph candidate DTOs/ports/builders, raw/page/ledger
  persistence/replay and the candidate manifest serializer. No dual writer or old-layout
  reader fallback remains; the historical publication adapter only supports migration
  history tests and rejects resource rows. Existing legacy active bases fail closed.
- T4.3: local reports and receipts provide bounded JSON transport for explicit retry and
  recovery (`--resources PATH`, Make `RESOURCES=PATH`); `--prior` takes the verified local
  report. No S3 metadata object is created. Default durable success requires exact
  three-file readback; local-only remains AWS-independent, failed persistence preserves
  files/report, and retained-all-excluded outcomes create no new durable generation.
- T4.4/T4.5: controlled tests prove exact three PUTs/three GETs, PostgreSQL keys/hash/bytes/
  rows and quality, workers1/2/3, sequential invalid/absent/wholly-excluded/outside-interval
  retention and valid replacement, upload/checksum/deadline/cancellation/bounds failures,
  joined staging cleanup, stale/forged owners, uncertain-commit reconciliation and explicit
  Admin retry. Public preview/SQL across all grains preserve precision, authorization,
  continuation pins and one-execution pagination through fixture subprocesses. API-only
  restart tests preserve healthy independently supervised work. Finding001 fixtures and
  negative architecture fixtures remain; superseded graph-only assertions were replaced
  with resource equivalents rather than keeping a production graph path.
- T4.C: `OUTAGE_TEST_POSTGRES_DSN` pointed to the existing disposable loopback PostgreSQL
  instance; installed Chromium was available. `make check` passed: dependency consistency,
  `.venv/bin/python -m ruff check .`, `.venv/bin/python -m ruff format --check .`
  (**420 files**), `.venv/bin/python -m mypy` (**147 source files**),
  `.venv/bin/python -m pytest -m 'not live_provider'` (**2,106 passed,39 skipped in97.24s**),
  and sdist/wheel build. The Make checkpoint ran the same non-live test command required by
  `make test`; no redundant full rerun was needed. Additional focused evidence includes
  **82 composed refresh/preview/query/HTTP/lifecycle tests**, **34 expanded refresh/recovery
  tests**, **205 connector tests** and migrated legacy/resource negative suites.
- AC1–AC6 verified within this controlled scope. No live EIA/AWS/RDS calls, managed migration,
  activation, deployment, historical object deletion, pointer reset, commit or push occurred
  as part of this phase. Estimated operation/storage reductions were not benchmarked;
  fixture subprocess tests do not certify actual-host isolation or production capacity.
- `git diff --check` reports existing trailing whitespace in concurrent append-only devlog
  entries; those historical/concurrent entries were preserved.
