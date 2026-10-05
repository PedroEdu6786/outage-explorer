# Tasks: Supervised connector integration and recovery
> Status: complete · Slug: data-api · Plan: ../plan.md · Spec: ../spec.md

## Phase 3 (plan phase 3)

- [x] **T3.1** Create admitted-run connector orchestration — `src/outage_explorer/application/services/refresh_execution.py`; compose existing candidate/replay/S3 ports using frozen settings and pinned published base; use committed trusted claims independently of browser lifetime. (FR13–FR15, FR18–FR24, TR8)
- [x] **T3.2** Create quality/status mapping — `src/outage_explorer/application/refresh_outcomes.py`; preserve disjoint dispositions, overlapping exclusion reasons, nullable unmeasured counts, all-three-excluded retention and bounded safe failures. Depends on T3.1. (FR16, FR21–FR24, FR29, TR8)
- [x] **T3.3** Create independent worker startup/composition — `src/outage_explorer/entrypoints/refresh_worker.py`, `src/outage_explorer/bootstrap.py`; poll/claim durably, renew fenced leases and shut down resources explicitly with no import/factory jobs. Depends on T3.1–T3.2. (FR13–FR15, FR25, TR8)
- [x] **T3.4** Create lost-owner reconciliation — `src/outage_explorer/application/services/refresh_recovery.py`; serialize with publication, recover historical committed success, keep unknown publication occupied, interrupt confirmed unpublished claimed work and leave source retry explicit. Depends on T3.3. (FR25–FR30, TR8)
- [x] **T3.5** Create controlled generation/restart/failure scenarios — `tests/integration/test_refresh_execution.py`, `tests/integration/test_refresh_recovery.py`; use real Parquet/PostgreSQL and controlled S3, API-only restarts, claim-before-first-fetch loss, failed/empty/corrupt input, changed config, stale epochs and historical publication. Depends on T3.4. (FR13–FR30, TR8)
- [x] **T3.C** Checkpoint: prove background independence, conservation/retention, atomic publication and recovery without source reruns — `tests/integration/test_refresh_execution.py`, `tests/integration/test_refresh_recovery.py`, `tests/architecture/test_import_boundaries.py`, `docs/specs/data-api/tasks/phase-3.md`; run Ruff/mypy and report environment limits separately. Depends on T3.5. (AC14–AC31)


Phase 3 evidence (2026-10-05): 125 focused execution/recovery/architecture
checks passed against disposable loopback PostgreSQL 18.6, real Parquet, and
controlled HTTP/S3. AC14–16 and AC26 verify committed all-grain admission,
frozen settings, browser logout independence and healthy worker survival across
separate API-process lifetimes; HTTP acknowledgement transport remains Phase 6.
AC17/22–25 verify disposition conservation, aggregated overlapping exclusion
reason occurrences, null unmeasured counts, invalid/absent/wholly excluded
retention, initial all-grain usability and failed/empty/corrupt/missing/resource
failures without partial publication. AC18–20 and AC27–31 reuse durable status,
atomic publication and serialized history recovery, adding real verified graphs,
claim-before-first-fetch loss, renewed leases, historical success after a later
publication, commit-response loss/rollback/unavailability and stale-source-owner
fencing without automatic source reruns. AC21 verifies immutable historical
publication references here; actual preview and retained SQL page tests remain
Phases 4–5. Narrow startup/type/encoding exceptions retain negative fixtures.

Repository-wide Ruff lint/format and strict mypy (98 source files) passed.
No live source work, cloud publication, RDS migration, deployment or measured
production-resource claim was performed. Linux query runtime evidence remains
Phase 1's separate open gate and does not block this controlled checkpoint.

Final regression with the installed Chromium cache passed: 1,411 tests and 17
subtests. The first run used Playwright's missing default browser location
(1,409 passed, one browser setup failure); setting the already provisioned
`PLAYWRIGHT_BROWSERS_PATH` resolved it without installing dependencies.
The final focused checkpoint also covers inert worker composition and rejects
forged owner identity before any graph/source I/O. Package sdist/wheel build and
`git diff --check` passed. Browser/provider tests used controlled transport.
