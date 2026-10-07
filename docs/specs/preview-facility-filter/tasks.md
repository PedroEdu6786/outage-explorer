# Tasks: Preview a dataset by date and facility
> Status: phases 1–3 complete; phase 4 pending · Slug: preview-facility-filter · Plan: ./plan.md · Spec: ./spec.md

## Overview

- 20 tasks across four phases; two tasks parallelizable [P]. Backend only; no web changes, service starts, live resources, deployment, image activation or publication.
- Complete and verify one phase per implementation run. Phases depend on the preceding checkpoint. New paths are explicitly identified below; all other paths exist.
- Keep the shipped HTTP parameter, catalog capabilities, OpenAPI pair and active fixtures date-only until Phase 3 completes the worker path. Phase 1 records the proposed contract separately; Phase 2 adds internal selection support without exposing an incomplete HTTP feature.

## Phase 1: Backend contracts and validation (plan phase 1)

- [x] **T1.1** [P] Create the proposed backend contract and labeled examples in `docs/specs/preview-facility-filter/contract.md` and `docs/specs/preview-facility-filter/contract-cases.json` (new). Describe exact opaque identity, 1–256 UTF-8 bytes, optional single facility on supported grains, combined inclusive dates, invalid/duplicate/national input, cursor-only continuation and planned catalog arrays. State explicitly that runtime support and active OpenAPI/fixtures arrive in Phase 3. (FR1–FR3, FR5, TR1, TR3)
- [x] **T1.2** [P] Add the shared pure identifier validator and explicit byte bound in `src/outage_explorer/domain/preview_filters.py` (new). Preserve strings exactly; reject nonstrings, empty values, surrounding whitespace, Unicode Cc controls (U+0000–001F and U+007F–009F), invalid UTF-8 and oversized values through a pure domain failure callers can translate. Use built-in operations without broadening allowed domain imports; do not add framework or application imports. (FR2, TR1, TR2)
- [x] **T1.3** Add behavior cases in `tests/unit/test_preview_filters.py` (new) for ASCII/multibyte byte boundaries, leading zeros, alphanumeric/case identity, quotes, controls, whitespace, lone surrogates and invalid types. Validate the proposed examples against the pure rule without asserting implemented HTTP or worker filtering. (FR1, FR2, TR1, TR2)
- [x] **T1.4** Add a clearly planned compatibility notice to `docs/specs/data-api/client-handoff.md`: strict two-date catalog decoders may reject the forthcoming capability expansion; backend delivery has no web implementation dependency. Link the proposed contract without advertising current facility support. (FR5, TR3)
- [x] **T1.C** Checkpoint: verify the proposed contract against AC1–AC2/AC5 requirements, run `tests/unit/test_preview_filters.py`, `tests/unit/test_data_api_contract.py`, `tests/integration/test_api_documentation.py` and `tests/architecture/`, plus Ruff/mypy. Confirm the active pair `docs/specs/data-api/openapi.json` / `src/outage_explorer/entrypoints/http/openapi.json` and `docs/specs/data-api/fixtures.json` still describe implemented date-only behavior. Record partial acceptance honestly in this file; AC1–AC6 are not complete. (AC1, AC2, AC5, AC6)

### Phase 1 checkpoint evidence — 2026-10-07

T1.1–T1.4 and T1.C completed. The proposed contract covers the AC1/AC2/AC5
requirements, with examples explicitly separated from runtime evidence. Pure
identifier validation and the existing date-only contract/documentation and
architecture suites passed: **312 tests**. Ruff lint/format and strict mypy
(**148 source files**) passed. The active OpenAPI pair and data API fixtures
remain unchanged and date-only. Facility filtering is not exposed by HTTP,
application sequences or workers in this phase; AC1–AC6 remain incomplete.
No PostgreSQL, Linux actual-host, web or live-resource checks ran.

## Phase 2: Application selection and cursor lifecycle (plan phase 2)

- [x] **T2.1** Extend `PreviewRead` in `src/outage_explorer/application/ports/execution.py` and `PreviewSequence`/creation in `src/outage_explorer/application/ports/preview_sequences.py` with optional immutable facility selection. Preserve omitted-filter callers and keep transport/engine details outside these ports. Update implementing adapters in `src/outage_explorer/infrastructure/worker_runtime/supervisor.py` and `src/outage_explorer/infrastructure/worker_runtime/unavailable.py` with the matching optional field and forwarding. (FR1, FR3, TR1)
- [x] **T2.2** Extend `src/outage_explorer/infrastructure/query_results/previews.py` to retain the selection and include its UTF-8 bytes in bounded sequence metadata accounting; preserve expiry, capacity rollback, owner checks, reader leases, pin release and unresolved reaping. (FR3, TR2)
- [x] **T2.3** Extend `src/outage_explorer/application/services/preview.py` to authorize first, validate the filter with the domain rule, reject national filtering and cursor/filter mixtures, and pass initial or stored selection to `PreviewRead`. Keep the HTTP route date-only until Phase 3; do not use the old worker as evidence that filtered requests work. (FR1–FR4, TR1, TR2)
- [x] **T2.4** Extend `tests/integration/test_catalog_preview.py` with observable injected execution ports proving exact selection propagation, direct-use-case validation, authorization before preparation/execution, immutable continuation/revisit selection, snapshot pins, 60-second expiry and facility-byte capacity exhaustion. Update `tests/fixtures/data_api/preview_worker.py` only as needed for unchanged date-only test compatibility; real filtered execution is Phase 3. (FR1–FR4, TR2)
- [x] **T2.C** Checkpoint: run `tests/integration/test_catalog_preview.py`, `tests/architecture/`, Ruff and mypy. Verify AC3–AC4 application/store behavior with call observation, while recording that actual worker equality and filtered HTTP acceptance remain incomplete. Confirm active catalog/HTTP contracts remain date-only. (AC3, AC4, AC6)

### Phase 2 checkpoint evidence — 2026-10-07

T2.1–T2.4 and T2.C completed. Preview requests and frozen sequences retain an
optional exact facility selection; the service authorizes before validation or
analytical access, applies the domain validator, and rejects national filters
and cursor/filter mixtures. Sequence admission charges facility UTF-8 bytes.
The supervised forwarding and unavailable adapters preserve the expanded port.

Portable injected execution-port tests verify AC3/AC4 application/store behavior:
selection/date/page-size propagation for both grains, stored continuation/revisit
selection, old-generation pins across fake publication, fixed 60-second expiry,
store loss, ownership and fresh role/session denials, capacity rollback and
unreaped-worker pin retention. These tests observe application orchestration;
they do not prove real worker facility equality or filtered HTTP acceptance.
The existing real-Parquet/date-only controlled subprocess test also passed.

**32 preview/lifecycle tests passed; 17 PostgreSQL-dependent cases were explicitly
deselected because no disposable test DSN was supplied.** Architecture and worker
response/transport suites passed **176 tests**. Ruff lint/format and strict mypy
(**148 source files**) passed. The old version-1 production transport now rejects
non-null facility selection instead of silently dropping it; a valid-file
regression proves the same unfiltered request is accepted. This narrow safeguard
is replaced by paired field transport in Phase 3. HTTP routes, catalog, paired
OpenAPI and active fixtures remain date-only; no services, database, Linux
actual-host or live-resource checks ran. AC1–AC6 remain incomplete for the full
feature, including the worker/HTTP portions of AC3/AC4.

## Phase 3: Isolated worker filtering (plan phase 3)

- [x] **T3.1** Extend paired request encoding and parent decoding in `src/outage_explorer/infrastructure/worker_runtime/decoding.py`, execution forwarding in `src/outage_explorer/infrastructure/worker_runtime/launcher.py`, strict worker decoding in `src/outage_explorer/infrastructure/worker_runtime/protocol.py`, and reviewed protocol identity in `src/outage_explorer/infrastructure/worker_runtime/configuration.py`. Carry an explicit nullable facility; independently validate it and supported grain, check returned facility equality, advance the paired version consistently for requests/responses/errors and reject old/mismatched versions without fallback. (FR1, FR2, TR1–TR3)
- [x] **T3.2** Add parameter-bound equality on the trusted public facility column in `src/outage_explorer/infrastructure/duckdb/previews.py`; combine dates and facility before keyset pagination. Preserve descending period/binary identifier order, streaming/bounds and the normal empty result for unknown valid IDs. (FR1–FR3, TR1, TR2)
- [x] **T3.3** Extend `tests/unit/test_worker_protocol.py`, `tests/unit/test_worker_response_decoding.py`, `tests/unit/test_analytical_runtime_configuration.py`, `tests/unit/test_docker_runtime.py`, `tests/integration/test_query_worker_transport.py`, `tests/integration/test_catalog_preview.py` and `tests/fixtures/data_api/preview_worker.py` for both grains, quotes as data, leading zeros, malformed/raw worker input, forged response identities and fail-closed paired-version mismatches. Update existing query/worker version fixtures consistently without weakening assertions. (FR1–FR3, TR1–TR3)
- [x] **T3.4** Expose the now-complete filter in `src/outage_explorer/entrypoints/http/data_schemas.py` and `src/outage_explorer/entrypoints/http/routes/datasets.py`; retain duplicate rejection and cursor-only continuation. Update `src/outage_explorer/application/services/catalog.py`, both `docs/specs/data-api/openapi.json` and `src/outage_explorer/entrypoints/http/openapi.json`, and `docs/specs/data-api/fixtures.json` together to advertise facility only for facilities/generators. Add matching request/catalog regressions in `tests/integration/test_data_api_http.py`, `tests/unit/test_data_api_contract.py` and `tests/integration/test_api_documentation.py`. (FR2–FR5, TR1, TR3)
- [x] **T3.C** Checkpoint: run the affected worker, preview, HTTP, contract and architecture suites plus Ruff/mypy. Prove real portable worker equality for AC1–AC2, ordered filtered pages for AC3, correct catalog/OpenAPI agreement and protocol rejection for AC5. Report any PostgreSQL-fixture cases not run with an explicit disposable DSN; do not build or activate a live image or claim actual-host isolation acceptance. (AC1–AC6)

### Phase 3 checkpoint evidence — 2026-10-07

T3.1–T3.4 and T3.C completed. The paired analytical request, success and error
protocol is now version **2**, with an explicit nullable facility field. Parent
encoding and worker decoding independently enforce exact bounded identity and
supported grain; parent decoding rejects rows from another facility. Version 1,
boolean and mismatched versions fail closed. Tabular encoding and the separate
SQL-inspection protocol remain version 1. The launcher already forwards the whole
`PreviewRead`; the existing pickle-based controlled preview fixture and application
selection/lifecycle tests already preserve its facility field and need no change.
Runtime profiles require protocol 2; existing pinned images/review identities need
rebuilding/review before use. No image was built or activated here.

Actual portable unified-Parquet/DuckDB subprocess cases verify AC1 worker behavior
for both grains: facility-only and inclusive-date intersection, leading-zero
identity, quotes as data, unmatched IDs, unchanged unfiltered/date-only results,
multiple ordered keyset pages and deterministic revisits. These tests prove the
worker predicate, not OS sandbox isolation. Separate portable HTTP cases use the
real `AccessService` and preview/store/lifecycle with observable injected execution
ports, proving facility/date/page forwarding, cursor continuation/revisit, validation
and current authorization before preparation/execution. Invalid raw UTF-8 is
rejected before Werkzeug can preserve it as a literal percent-escaped identifier;
a legitimately escaped literal percent identifier remains valid. The architecture
exception permits only `urllib.parse.unquote_to_bytes`; negative fixtures continue
to reject network and broad urllib imports. National filtering, duplicate input,
malformed identifiers, cursor/filter mixtures and forged worker identities are
rejected. Catalog, active fixtures and paired OpenAPI advertise facility only on
the two supported grains (AC2/AC5); application lifecycle evidence from Phase 2
and real ordered worker pages cover this phase's AC3 portions.

Checkpoint commands: `.venv/bin/python -m ruff check .`,
`.venv/bin/python -m ruff format --check .` (**447 files**),
`.venv/bin/python -m mypy src` (**148 source files**) all passed.
The clean full portable run used a temporary collection plugin to deselect tests
requiring the `database` fixture:
`PYTHONPATH=/private/tmp:src .venv/bin/python -m pytest -q -rs -p outage_preview_nodb -m 'not live_provider'`.
Result: **2,283 passed, 41 skipped, 194 deselected, 17 subtests passed**.
All 194 deselections were PostgreSQL fixture cases, including the existing
17 preview and 7 HTTP cases. Skips were 20 explicitly opt-in Docker/runtime
acceptance cases, 18 Linux `prlimit` cases, one Linux path-descriptor case and two
additional explicit-disposable-PostgreSQL cases. No disposable test DSN was supplied.
An initial broad run exposed one obsolete mocked transport assertion treating
facility as an unknown field; its transport-level rejection now tests repeated
facility parameters, while actual application tests prove national rejection.
The clean full run includes that correction, architecture, worker, HTTP and
contract suites. No services, live resources, PostgreSQL, native Linux host checks,
web work, deployment or publication ran. Full feature AC1–AC6 checkboxes stay open
until Phase 4 consolidates cross-layer coverage, documentation and evidence.

## Phase 4: Backend verification and documentation (plan phase 4)

- [ ] **T4.1** Complete cross-layer regression cases in `tests/integration/test_catalog_preview.py` and `tests/integration/test_data_api_http.py`: concatenate multiple filtered pages for both grains, revisit pages, publish a fake new snapshot, reject cursor-plus-filter, preserve unfiltered/date-only results, and deny Viewer/absent/expired/revoked/foreign-cursor/changed-role access before preparation or execution. Retain active-reader/reaping/store-loss checks alongside new filters. (FR1–FR4, TR2)
- [ ] **T4.2** Synchronize `docs/specs/data-api/http-contract.md`, `docs/specs/data-api/preview-flow.md`, `docs/specs/data-api/client-handoff.md`, `docs/context/ui-client/02-web-experience.md`, `docs/context/ui-client/04-backend-integration.md`, `docs/context/architecture.md`, `docs/context/overview.md` and `docs/specs/outage-explorer-backend/spec.md` with implemented backend filtering and consumer compatibility. Correct obsolete preview manifest references to exact three-resource staging; consumer handoff documents the API only and introduces no web-project work. Mark the feature contract as implemented only to the extent verified. (FR5, TR1–TR3)
- [ ] **T4.3** Update paired protocol/image prerequisites in `infrastructure/analytical-worker/README.md` and applicable fixture/profile generation in `infrastructure/analytical-worker/native-linux-validation/create-profile.py`, `tests/test_local_analytical.py` and `tests/acceptance/test_query_runtime.py`. State that existing pinned image/review identity must be rebuilt/reviewed for the new protocol before use; do not invent a digest, modify historical evidence or activate/build deployment resources during this feature implementation. (TR2, TR3)
- [ ] **T4.4** Record current results and remaining evidence gaps in `docs/specs/preview-facility-filter/verification.md` (new) and update acceptance status in `docs/specs/preview-facility-filter/spec.md`. Separate portable behavior, explicit disposable-PostgreSQL results and unavailable Linux actual-host checks; retain broader runtime/capacity gaps and backend-only scope. (FR1–FR5, TR1–TR3)
- [ ] **T4.C** Checkpoint: verify AC1–AC6 against actual evidence in `docs/specs/preview-facility-filter/verification.md`, run documented Ruff/mypy, `tests/architecture/` and relevant pytest suites, check paired OpenAPI/fixtures and documentation links, and run disposable PostgreSQL cases only when an explicit test DSN is supplied. Report skips/unavailable checks and protocol/image prerequisites without implying production readiness or web acceptance. (AC1–AC6)
