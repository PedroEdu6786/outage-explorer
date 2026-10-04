# Phase 4: Runnable local connector
> Status: complete (local checkpoint, 2026-10-04) · Plan phase: 4 · Depends on: completed phases 1–3

Configuration follow-up: [ADR-0041](../../../adr/0041-connector-defaults-and-json-configuration.md)
replaces the environment-budget interface in the historical tasks below with
typed defaults and optional `--config PATH` JSON overrides. The original phase
checkpoint remains historical evidence; follow-up verification is recorded below.

- Scope: one contributor CLI joins existing EIA, Python validation and PyArrow adapters into verified local candidate output. Controlled tests need no PostgreSQL, Cognito, S3 or EC2 connection; this phase adds no product publication or DuckDB execution.
- Paths marked **new** are intended additions under the existing layer-first layout. `[P]` tasks can run together after T4.1; all other dependencies are stated explicitly.

- [x] **T4.1** Add connector request/result DTOs and safe failure codes in `src/outage_explorer/application/dto.py` and `src/outage_explorer/application/errors.py`, and create narrow source-factory, evidence/manifest and report ports in **new** `src/outage_explorer/application/ports/connector.py`; reuse existing source/candidate/artifact contracts. Carry explicit dates, bounds, generated identities and optional exact prior-manifest reference; distinguish `candidate_verified`, `retained_all_excluded` and `failed`, always without publication. (FR4–FR6, FR14–FR16, FR18 candidate portion; TR1, TR4–TR6, TR9)
- [x] **T4.2** [P] Create explicit environment parsing in **new** `src/outage_explorer/settings.py` and document variables in `.env.example`; use `EIA_API_KEY` only from the environment, validate source/artifact/modeling/report budgets and interval inputs before filesystem/network work, and exclude secrets from representations/errors. Fixture construction uses injected configuration without real credentials; test caps are not measured production defaults. Depends on T4.1. (FR5, FR6; TR4–TR6)
- [x] **T4.3** [P] Create the evidence/manifest adapter in **new** `src/outage_explorer/infrastructure/parquet/connector.py`; wrap existing evidence writing, exact-reference manifest loading/persistence and verification behind T4.1 ports. Verify the pinned prior graph before retrieval, preserve immutable earlier output and bounded streaming, and reopen/verify the persisted result; reuse `src/outage_explorer/infrastructure/parquet/storage.py` without a mutable local active pointer. Depends on T4.1. (FR6–FR12, FR18 candidate portion; TR1–TR5, TR9, TR10)
- [x] **T4.4** [P] Create bounded progress/final-report output in **new** `src/outage_explorer/infrastructure/connector_report.py`; record interval, execution identity, stage, safe errors, verified manifest reference, per-grain source/model quality and limitations. Keep source totals, received/excluded/reason/retained counts distinct; omit keys, raw exceptions and request URLs. Preserve earlier reports in separate run output; report-write failure cannot claim completion. Depends on T4.1. (FR5, FR6, FR14–FR16, FR18 candidate portion; TR4, TR5)
- [x] **T4.5** Create the candidate use case in **new** `src/outage_explorer/application/services/connector.py`; verify any explicit prior candidate, retrieve all three routes sequentially, persist sanitized evidence, require terminal source quality, build/verify/reopen the candidate and write its report through ports. Reuse retention, selection and exact arithmetic; require usable output in every grain without prior data. Separate retrieval/resource/representation/report failures from exclusions and preserve earlier candidates. Depends on T4.1–T4.4. (FR4–FR16, FR18 candidate portion; TR1–TR9)
- [x] **T4.6** Add construction and cleanup in `src/outage_explorer/bootstrap.py`; validate configuration before constructing transport/storage, inject per-route source factories, identities and adapters, and close the caller-owned transport on success/failure. Preserve controlled-transport injection; imports and HTTP factories perform no connector work. Depends on T4.2–T4.5. (FR4–FR6; TR1, TR4, TR5)
- [x] **T4.7** Create the thin command in **new** `src/outage_explorer/entrypoints/cli/connector.py` and **new** `src/outage_explorer/entrypoints/cli/connector_startup.py`, and register it in `pyproject.toml`; accept explicit inclusive dates, staging location and optional exact prior reference, invoke the constructed service and return documented exit codes. Help needs no credentials/I/O; outputs are sanitized and never imply active publication. Depends on T4.6. (FR4, FR5, FR14–FR16; TR1, TR4–TR6, TR9)
- [x] **T4.8** Extend only the connector startup exception in `tests/architecture/import_rules.py` and negative fixtures in `tests/architecture/test_import_boundaries.py`; update `tests/integration/test_startup.py` to prove imports/help and HTTP construction cannot fetch EIA, touch storage or start connector work. Preserve existing startup restrictions and offline verifier behavior. Depends on T4.7. (TR1, TR4, TR5)
- [x] **T4.9** Add orchestration tests in **new** `tests/unit/test_connector_service.py` and configuration tests in **new** `tests/unit/test_connector_settings.py`; verify invalid configuration/prior state before retrieval, terminal source quality before modeling, failure/report semantics and all-excluded/no-prior policies through injected ports. Depends on T4.2–T4.6. (FR4–FR11, FR14–FR16, FR18 candidate portion; TR4–TR6, TR9)
- [x] **T4.10** Add CLI-to-real-Parquet integration in **new** `tests/integration/test_connector_cli.py` using controlled multipage transports across all grains; reopen with EIA disabled and verify source strings/order, cross-page A/B/A/duplicates, independent calculations and quality counts. Cover both facility-total mismatches and failed-page counterparts, invalid config before I/O, secret-free logs/reports and failure exit codes. Depends on T4.7–T4.9. (FR4–FR8, FR12–FR16; TR1–TR5, TR7, TR8)
- [x] **T4.11** Add rerun/failure integration in **new** `tests/integration/test_connector_reruns.py`; pin a verified prior candidate, repeat without duplicate keys, replace valid revisions and preserve invalid/absent/outside-interval origins and wholly excluded routes. Reject unusable initial grains; inject page/budget/representation/corrupt-graph/interrupted-write/report failures and prove earlier candidates still reopen. Equal inputs need not produce byte-identical manifests because identities/timestamps are evidence; no outcome says published. Depends on T4.10. (FR5, FR9–FR12, FR16, FR18 candidate portion; TR2–TR6, TR9, TR10)
- [x] **T4.12** Document command usage, configuration, report/exit meanings, explicit-prior reruns and failures in `README.md`; synchronize current composition in `docs/context/code-structure.md`, `docs/context/architecture.md` and `docs/specs/data-connector/plan.md`. Distinguish contributor candidates from initial live loading and backend activation; fixtures prove no live guarantees. Depends on T4.8–T4.11. (FR4–FR16; TR1, TR4–TR9)
- [x] **T4.C** Checkpoint: run documented `make check` from `README.md`, including `tests/unit/test_connector_service.py`, `tests/unit/test_connector_settings.py`, `tests/integration/test_connector_cli.py`, `tests/integration/test_connector_reruns.py`, startup/architecture checks and source/Parquet/verifier regressions; record actual results in `docs/specs/data-connector/tasks/phase-4.md`. Verify AC3–AC15 local candidate/report portions and AC17 local integrity/failure portions without credentials/network. Authorization, active-generation guarantees, live validation and cloud durability remain unproven. Depends on T4.12. (AC3–AC15, AC17; TR1–TR9)


## Recorded checkpoint — 2026-10-04

T4.1–T4.12 and T4.C completed. `make check` passed on Python 3.14.6:

- Dependency validation: no broken requirements.
- Ruff lint and format: passed (163 files formatted).
- Strict mypy: passed (52 source files).
- Pytest: **687 passed in 50.34 seconds**, no failures or skips. The four new
  connector test modules contribute **90 tests**: 18 service, 43 configuration,
  9 CLI/Parquet and 20 rerun/failure tests. The full run also exercised startup,
  architecture negative fixtures and existing source, Parquet, offline verifier,
  health and devlog regressions, including pre-existing uncommitted phase-3 work.
- Wheel and source distribution: built successfully with `--no-isolation`.
- Local editable registration succeeded without dependency installation; both
  module invocation and `.venv/bin/build-connector-candidate --help` returned 0
  without connector work. Wheel metadata contains the registered console command.
- `git diff --check` passed. No commits, pushes, live EIA requests, cloud/database
  writes or deployment were performed. Existing unrelated changes were preserved.

| Criteria | Verified local evidence |
| --- | --- |
| AC3–AC5 | Sequential controlled multipage retrieval across all grains, terminal quality required before modeling, raw strings/positions/identities replayed, credential-bearing echoes sanitized, safe failure codes and explicit budgets. Reopen checks forbid EIA construction. Existing source tests cover malformed/nonprogressing responses and individual retrieval bounds. |
| AC6–AC7 | Existing validation regressions plus CLI cross-page A/B/A, duplicate and later-invalid observations; exact source order and winner retained with zero values usable. |
| AC8–AC9 | Explicit-prior repeated/changed input, unique modeled keys, valid replacement, and original invalid/absent/outside-interval provenance. |
| AC10–AC11 | Unusable/empty initial grains fail; partial and all-excluded retention remain distinct; exact reopened candidates retain existing cross-file uniqueness verification. No test activates a generation. |
| AC12 | Independent national/facility/generator values, source numeric strings and exact fractional calculations survive real Parquet. |
| AC13–AC15 | Separate source/model quality and reason counts reconcile; observed coverage remains unverified completeness. Controlled facility 2,850 advertised/1,650 received is nonblocking; a failed-page counterpart fails. |
| AC17 | Corrupt prior graphs fail before retrieval; page, budget, representation, interrupted immutable write, report-byte and report-write failures preserve earlier candidates. Report cleanup cannot contradict an already-linked final report. |

Reports and candidates are local contributor artifacts, always with no
publication. Full-spec acceptance checkboxes remain open: Admin authorization,
active-generation preservation/activation, durable backend outcomes, supervision,
reader pinning, live paging/order/applicability, measured production limits and
S3/cloud durability have not been established by this checkpoint. An abrupt kill
may leave progress and unreferenced immutable objects, never a confirmed final
outcome. Initial product loading still requires the accepted April 2–October 1,
2026 interval through the later authorized backend lifecycle.

Next: Review the diff, then run /implement for phase 5.

## Configuration follow-up — 2026-10-04

- Implemented immutable typed defaults, optional partial/full JSON configuration,
  and explicit run-flag precedence under ADR-0041. Removed budget environment
  handling; the EIA key remains environment-only. Dates/staging remain required
  from flags or file. JSON size, schema, duplicate keys and integer limits are
  validated before constructing storage/HTTP adapters.
- Added `connector.config.example.json`, updated usage and living context, and
  migrated budget-failure tests to file overrides. Controlled CLI tests exercise
  file-only runs, flag precedence, default-only runs, malformed files and help
  without configuration reads. Original phase scope and deferred guarantees stay
  unchanged.
- `make check` passed: dependency validation, Ruff lint/format, strict mypy,
  **750 tests without skips**, wheel and sdist builds. The focused configuration,
  CLI/rerun, startup and architecture run passed **207 tests**. Installed help,
  offline example validation, local documentation links and diff whitespace also
  passed. No live requests, cloud/database writes, commits or pushes.
