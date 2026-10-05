# Tasks: HTTP integration and combined acceptance
> Status: complete (controlled checkpoint); user-owned runtime validation separate · Slug: data-api · Plan: ../plan.md · Spec: ../spec.md

## Phase 6 (plan phase 6)

- [x] **T6.1** Create strict transport schemas and data error mapping — `src/outage_explorer/entrypoints/http/data_schemas.py`, `src/outage_explorer/entrypoints/http/errors.py`; reject unknown/duplicate parameters, invalid dates/integers and unsupported bodies, bound requests and serialize frozen lossless envelopes with safe retry hints. (FR1–FR17, FR29, TR1–TR4)
- [x] **T6.2** Create thin dataset/query/refresh routes — `src/outage_explorer/entrypoints/http/routes/datasets.py`, `src/outage_explorer/entrypoints/http/routes/queries.py`, `src/outage_explorer/entrypoints/http/routes/refresh.py`; mount seven method contracts using injected application services without storage/engine calls. Depends on T6.1. (FR1–FR17, FR29, TR1–TR4)
- [x] **T6.3** Update browser transport and inert composition — `src/outage_explorer/entrypoints/http/auth_transport.py`, `src/outage_explorer/entrypoints/http/app.py`, `src/outage_explorer/bootstrap.py`, `src/outage_explorer/settings.py`; reuse CSRF/current sessions, exact credentialed CORS/no-store, refresh idempotency preflight and exposed Location/Retry-After, explicit cleanup and runtime enablement gates. Depends on T6.2. (FR1, FR11–FR15, FR25, TR1, TR5–TR8)
- [x] **T6.4** Create HTTP contract and combined process acceptance — `tests/integration/test_data_api_http.py`, `tests/acceptance/test_data_api_lifecycle.py`; exercise current roles/ownership, cursor/result loss, all outcome envelopes, durable acknowledgement, publication/recovery races and refresh/query overlap with real configured bounds. Depends on T6.3. (FR1–FR30, TR1–TR9)
- [x] **T6.5** Update frontend handoff, runtime evidence and living context — `docs/specs/data-api/openapi.json`, `docs/specs/data-api/fixtures.json`, `docs/specs/data-api/http-contract.md`, `docs/specs/data-api/runtime-evidence.md`, `docs/context/code-structure.md`, `docs/context/architecture.md`, `README.md`; reconcile actual endpoints/limits against Phase 1 artifacts and publish reproducible local commands without implying deployment. Depends on T6.4. (FR1–FR30, TR1–TR9)
- [x] **T6.C** Checkpoint: run full documented Ruff, formatting, mypy, pytest and package checks, including import-boundary negative fixtures and real runtime/combined acceptance — `tests/integration/test_data_api_http.py`, `tests/acceptance/test_data_api_lifecycle.py`, `tests/acceptance/test_query_runtime.py`, `tests/architecture/test_import_boundaries.py`, `docs/specs/data-api/tasks/phase-6.md`; map every AC to actual evidence and leave unavailable live/environment checks explicit. Deployment/frontend implementation remain separate. Depends on T6.5. (AC1–AC33)


## Checkpoint scope and evidence

The user owns T1.7 and directed agents to skip that validation. T6.1–T6.5 are
implemented; T6.C records the authorized controlled checkpoint, with unavailable
runtime/live evidence explicit in [runtime-evidence.md](../runtime-evidence.md).
The evidence map covers every AC1–AC33; AC8 OS isolation and AC33 actual worker-tree
termination/measurements remain user-owned and are not marked proven.

- 45 PostgreSQL HTTP/refresh/coordination regression tests passed.
- 2 controlled HTTP combined lifecycle tests passed.
- 226 portable transport/contract/architecture tests passed.
- Dependency consistency, Ruff lint/format, strict mypy (126 files) and package
  sdist/wheel build passed.
- Full configured non-live regression: **1,556 passed plus 17 subtests**
  (242.16 seconds), using disposable PostgreSQL and installed Chromium.
- Final disabled-port correction removes placeholder execution/sequence budgets;
  affected portable/startup/static checks reran after the full regression.

No live migration, deployment, publication, frontend repository edit or push was
performed. Runtime and capacity proposals retain their existing status.
