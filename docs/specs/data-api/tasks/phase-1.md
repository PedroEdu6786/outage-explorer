# Tasks: Contract and runtime feasibility
> Status: portable work complete; runtime gate pending · Slug: data-api · Plan: ../plan.md · Spec: ../spec.md

## Phase 1 (plan phase 1)

- [x] **T1.1** Update the selected wire vocabulary and reconcile draft contradictions — `docs/specs/data-api/http-contract.md`, `docs/specs/data-api/spec.md`; freeze seven route/method inputs, output fields, date/cursor rules, refresh/idempotency semantics and error codes, including per-user 429/global 503 retention capacity and existing generic auth denial. Keep runtime/quotas explicitly unreviewed. (FR1–FR30, TR1–TR9)
- [x] **T1.2** Create portable frontend schema and synthetic response fixtures — `docs/specs/data-api/openapi.json`, `docs/specs/data-api/fixtures.json`, `tests/unit/test_data_api_contract.py`; cover permitted catalogs, previews, lossless values, duplicate SQL labels, empty/truncated/direct/revisited pages, explicit errors and every refresh status including null quality/latest. Validate schemas and examples against each other; label endpoints as pending. Depends on T1.1. (FR2, FR4–FR6, FR9–FR17, FR22, FR29, TR1–TR4, TR9, AC2, AC6, AC13, AC18)
- [x] **T1.3** [P] Create shared public projection definitions and verify them against implemented Parquet schemas — `src/outage_explorer/domain/datasets.py`, `tests/unit/test_public_datasets.py`; map plural public names to existing grain enums, preserve string identifiers and exact national arithmetic/presentation fields, and hide provenance/storage columns. Depends on T1.1; independent of T1.4. (FR2, FR6, TR9, AC2, AC6)
- [x] **T1.4** [P] Pin and verify parser/engine dependencies — `pyproject.toml`, `requirements-dev.txt`, `tests/integration/test_sql_compatibility.py`; exercise real DuckDB in controlled tests only, covering joins, CTE scopes including recursion, set operations, subqueries, windows, duplicate labels and representative scalar/nested engine values. Depends on T1.1; independent of T1.3. (FR7–FR8, TR7, AC7, AC8)
- [x] **T1.5** Create parser-owned reference inspection behind an application port — `src/outage_explorer/application/ports/sql_inspection.py`, `src/outage_explorer/infrastructure/sql_validation/inspection.py`, `tests/unit/test_sql_inspection.py`; resolve complete dataset references without rewriting SQL, reject writes/configuration/external/system/dynamic access and cover CTE shadowing plus explicit reference-free authorization requirements. Document demonstrated parser gaps rather than silently shrinking analytical scope. Depends on T1.3, T1.4. (FR1, FR7–FR8, TR1, TR7, AC7, AC8)
- [x] **T1.6** Create canonical lossless tabular encoding and byte-accounting fixtures — `src/outage_explorer/infrastructure/query_results/encoding.py`, `tests/unit/test_query_encoding.py`, `tests/integration/test_sql_compatibility.py`; preserve ordered columns/row arrays and recursive types, exact integers/decimals, temporal/binary/nonfinite values, contiguous complete-row prefixes, schema overhead and oversized-first-row distinctions. Bound recursive expansion and verify the exact 1,000-row/1,048,576-byte limits with real engine values. Depends on T1.2, T1.4. (FR6–FR9, FR12, TR3–TR4, TR7, TR9, AC6, AC7, AC32)
- [ ] **T1.7** Create runtime feasibility evidence and reproducible test profile — `docs/specs/data-api/runtime-evidence.md`, `tests/acceptance/test_query_runtime.py`; record platform/tool availability, then verify a concrete Linux launcher's file/network/credential denial, memory/process/disk limits and whole-worker termination/reaping before selection. Measure cold/warm preparation, encoding/storage and combined query/refresh workloads; record reviewed topology/quotas only after actual evidence. Unsupported environments leave these checks explicitly pending and real SQL disabled; controlled subprocess tests are not isolation proof. Depends on T1.4–T1.6. (FR8, FR11–FR12, FR19–FR20, FR24, TR5–TR7, AC8, AC12, AC33)
- [ ] **T1.C** Checkpoint: run relevant contract, projection, parser/engine, encoding and architecture tests plus Ruff/mypy — `tests/unit/test_data_api_contract.py`, `tests/unit/test_public_datasets.py`, `tests/unit/test_sql_inspection.py`, `tests/unit/test_query_encoding.py`, `tests/integration/test_sql_compatibility.py`, `tests/architecture/test_import_boundaries.py`, `docs/specs/data-api/tasks/phase-1.md`; record frontend handoff readiness separately from measured runtime readiness. AC2/AC6/AC7/AC8/AC13/AC18/AC32 are phase-scoped contract/adapter evidence, not endpoint acceptance; full Phase 1 remains open until T1.7 proves AC33 and isolation. Depends on T1.1–T1.7. (AC2, AC6–AC8, AC13, AC18, AC32, AC33)

## Checkpoint evidence

- Validation ownership (2026-10-05): the user will perform T1.7 validation.
  Agents should skip executing this validation step and continue independent
  implementation. T1.7/T1.C remain unchecked pending the user's results;
  assigning validation does not supply runtime evidence.
- T1.1–T1.6 complete: selected wire vocabulary, portable OpenAPI and synthetic
  examples for all seven operations, Parquet projection parity, pinned parser/
  engine reference analysis, and bounded canonical encoding.
- Phase-scoped AC2/AC6/AC7/AC8/AC13/AC18/AC32 evidence is contract/adapter-only.
  It does not establish HTTP authorization, publication or real worker isolation.
- T1.7 is pending: Darwin host and missing Docker daemon socket prevented Linux
  sandbox denial/termination/limits and measured overlap checks. No product SQL
  runtime, topology or proposed retention quota was enabled.
- T1.C remains open because runtime AC8/AC33 evidence is absent. Independent
  frontend work can use [the handoff](../client-handoff.md); see
  [runtime evidence](../runtime-evidence.md) for exact limitations.
- Verification: `make check` passed pip dependency checks, Ruff lint/format,
  mypy (84 source files), full pytest (1,244 passed, 25 skipped), and sdist/wheel
  build. The 25 skipped tests require explicit disposable PostgreSQL configuration
  (`OUTAGE_TEST_POSTGRES_DSN`); they are existing access-storage integration tests.
- A final temporal-extreme guard was added after full-suite collection; affected
  encoding/real-engine tests were rerun separately: 22 passed. Final Ruff/format,
  mypy and diff-whitespace checks passed. The earlier targeted contract/projection/
  parser/encoding/engine/architecture checkpoint passed 222 tests.
- Linux isolation, measured preparation/storage/overlap, live browser/provider
  integration, deployment and publication were not run. Phase 1 remains partial;
  these results establish the client handoff, not production execution readiness.
