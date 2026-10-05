# Tasks: Supervised connector integration and recovery
> Status: pending · Slug: data-api · Plan: ../plan.md · Spec: ../spec.md

## Phase 3 (plan phase 3)

- [ ] **T3.1** Create admitted-run connector orchestration — `src/outage_explorer/application/services/refresh_execution.py`; compose existing candidate/replay/S3 ports using frozen settings and pinned published base; use committed trusted claims independently of browser lifetime. (FR13–FR15, FR18–FR24, TR8)
- [ ] **T3.2** Create quality/status mapping — `src/outage_explorer/application/refresh_outcomes.py`; preserve disjoint dispositions, overlapping exclusion reasons, nullable unmeasured counts, all-three-excluded retention and bounded safe failures. Depends on T3.1. (FR16, FR21–FR24, FR29, TR8)
- [ ] **T3.3** Create independent worker startup/composition — `src/outage_explorer/entrypoints/refresh_worker.py`, `src/outage_explorer/bootstrap.py`; poll/claim durably, renew fenced leases and shut down resources explicitly with no import/factory jobs. Depends on T3.1–T3.2. (FR13–FR15, FR25, TR8)
- [ ] **T3.4** Create lost-owner reconciliation — `src/outage_explorer/application/services/refresh_recovery.py`; serialize with publication, recover historical committed success, keep unknown publication occupied, interrupt confirmed unpublished claimed work and leave source retry explicit. Depends on T3.3. (FR25–FR30, TR8)
- [ ] **T3.5** Create controlled generation/restart/failure scenarios — `tests/integration/test_refresh_execution.py`, `tests/integration/test_refresh_recovery.py`; use real Parquet/PostgreSQL and controlled S3, API-only restarts, claim-before-first-fetch loss, failed/empty/corrupt input, changed config, stale epochs and historical publication. Depends on T3.4. (FR13–FR30, TR8)
- [ ] **T3.C** Checkpoint: prove background independence, conservation/retention, atomic publication and recovery without source reruns — `tests/integration/test_refresh_execution.py`, `tests/integration/test_refresh_recovery.py`, `tests/architecture/test_import_boundaries.py`, `docs/specs/data-api/tasks/phase-3.md`; run Ruff/mypy and report environment limits separately. Depends on T3.5. (AC14–AC31)
