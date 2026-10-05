# Tasks: Authorized catalog and stable previews
> Status: controlled implementation complete; real runtime gate pending · Slug: data-api · Plan: ../plan.md · Spec: ../spec.md

## Phase 4 (plan phase 4)

- [x] **T4.1** Create published-input/cache ports and verified modeled-file adapter — `src/outage_explorer/application/ports/analytical_inputs.py`, `src/outage_explorer/infrastructure/local_cache/modeled.py`; resolve published manifests only, verify identity/schema/checksums, bound download/cache budgets and pin active files without exposing raw/provenance graphs. (FR3, FR19–FR20, TR5, TR7–TR9)
- [x] **T4.2** Create isolated execution port and verified-launcher adapter — `src/outage_explorer/application/ports/execution.py`, `src/outage_explorer/infrastructure/worker_runtime/launcher.py`, `src/outage_explorer/entrypoints/query_worker.py`; accept exact approved files/projections and budgets, reserve one slot through reaping and fail closed without reviewed runtime. Depends on T4.1 and T1.7 for real execution. (FR7–FR8, FR12, TR5, TR7)
- [x] **T4.3** [P] Create role-filtered catalog service — `src/outage_explorer/application/services/catalog.py`; resolve current access before publication metadata, reuse shared projections and avoid accidental empty-grain denial/bypass. Depends on Phase 1 projection and Phase 2 ports; independent of T4.2. (FR1–FR3, FR6, TR1, TR9)
- [x] **T4.4** Create bounded preview-sequence store and authenticated cursors — `src/outage_explorer/application/ports/preview_sequences.py`, `src/outage_explorer/infrastructure/query_results/previews.py`; bind user/grain/generation/dates/order/size and fixed 15-minute lifetime, support visited cursors and independent count/byte quotas. Depends on T4.1. (FR5, FR10–FR11, FR20, TR1–TR2, TR6)
- [x] **T4.5** Create authorized date-only preview service — `src/outage_explorer/application/services/preview.py`; normalize inclusive/unbounded dates, use verified keys and binary identifier ordering, reauthorize each continuation, enforce response bytes without skipping and execute through the isolated port. Depends on T4.2–T4.4. (FR1, FR3–FR6, FR10, FR12, FR19–FR20, TR1–TR2, TR5, TR9)
- [x] **T4.6** Create controlled preview/catalog integration tests — `tests/integration/test_catalog_preview.py`; cover all roles, expiry/tampering, exact tie order, 100/500 sizes, empty filters, old generations after publication and source-unavailable reads. Depends on T4.5. (FR1–FR6, FR10–FR12, FR19–FR20)
- [x] **T4.C** Checkpoint: verify publication-only browsing, current authorization, stable cursors and national projection — `tests/integration/test_catalog_preview.py`, `tests/architecture/test_import_boundaries.py`, `docs/specs/data-api/tasks/phase-4.md`; run Ruff/mypy and distinguish controlled execution tests from real launcher evidence. Depends on T4.6. (AC1–AC6, AC11, AC13, AC20–AC21, AC33)


## Checkpoint evidence

- T4.1–T4.6 implementation is present. The catalog explicitly authorizes its
  role-derived nonempty scope before publication lookup. Preview authorizes
  every initial/continuation call, retains the original generation and uses
  binary UTF-8 identifier keyset ordering through the isolated execution port.
- The cache downloads only publication manifests and selected modeled objects,
  verifies physical schemas, semantic modeled rows, natural keys, checksums,
  row counts and coverage, and produces worker files containing public columns
  only. Independent row/file/byte/preparation budgets and active pins prevent
  unbounded downloads and removal of active generations.
- Cursor metadata has independent count/byte quotas, authenticated visited-page
  cursors, exact fixed 15-minute expiry and explicit supervised cleanup.
  Cleanup waits for active pages; failed reaping retains both the execution
  slot and the active input pin rather than assuming the worker has exited.
- Controlled AWS/database-independent verification: 105 tests passed across
  `test_catalog_preview.py` and architecture boundaries; 17 PostgreSQL-dependent
  catalog/preview cases skipped without explicit local DSN. The real-Parquet
  smoke test uses a synthetic publication port and a separate controlled
  DuckDB process across all three grains; it is not OS isolation evidence.
- Ruff lint/format, strict mypy (113 source files), and whitespace checks pass.
  A broader unconfigured non-live run passed 1,344 tests and 17 subtests,
  skipped 53 and had 35 existing PostgreSQL/acceptance setup errors because
  `OUTAGE_TEST_POSTGRES_DSN` was absent. It is not a passing full-suite claim.
- T4.C passed with approved disposable PostgreSQL: 22 catalog/preview tests
  passed in 85.15 seconds, alongside 100 architecture tests. These establish
  controlled AC1–AC6, AC11, AC13 and AC20–AC21 application/adapter behavior;
  HTTP/error-envelope and SQL-specific acceptance remain later phases.
- The first configured checkpoint exposed a synthetic source ordering error:
  its second-refresh national rows were descending while EIA retrieval requires
  ascending order. Correcting the fixture made the generation-stability test
  pass; preview ordering remains independently newest-first. Initial sandbox
  networking/approval interruptions did not provide execution evidence.
- Product runtime remains unconfigured and fails closed before preparation.
  T1.7 still requires reviewed Linux denial/limits/kill/reap and measured
  preparation/storage/overlap evidence. Controlled busy/reap tests establish
  only the adapter contract portion of AC33. No HTTP endpoints, deployment,
  live data publication or production runtime approval were added.
