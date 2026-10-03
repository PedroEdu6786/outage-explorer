# Phase 2: Parquet schemas, replay and candidate verification
> Status: complete (local candidate checkpoint) · Plan phase: 1 (storage completion) · Depends on: phase 1

- [x] **T2.1** Resolve/pin the Parquet dependency in `pyproject.toml` and `requirements-dev.txt`, and record the selected physical schema/version in `docs/specs/data-connector/plan.md`; verify widths and exact round trips under the accepted typed-decimal/source-string/fail-on-loss direction. (TR1–TR3)
- [x] **T2.2** [P] Add explicit raw/page/disposition/modeled/merge-ledger schemas and exact representability checks in `src/outage_explorer/infrastructure/parquet/schemas.py`; preserve numeric strings, exact ratios, required units and origin identities. Otherwise-valid decimal/projection overflow or scale loss fails the candidate without adding exclusions. (FR6, FR7, FR13; TR1–TR4)
- [x] **T2.3** [P] Add transport-independent candidate/artifact/manifest contracts in `src/outage_explorer/application/ports/candidates.py` and `src/outage_explorer/application/ports/artifacts.py`; manifests name exact objects, hashes/counts, partitions, versions and inherited evidence dependencies. (FR6, FR12, FR17–FR20; TR1, TR4, TR10)
- [x] **T2.4** Add bounded raw/page/disposition writers and replay in `src/outage_explorer/infrastructure/parquet/evidence.py`; retain sanitized JSON types/strings, empty-page records, ordering and request identity, and fail explicitly on staging/output limits. Sanitization is an upstream contract tested again in phase 3. (FR6, FR7, FR8; TR1, TR4, TR5, TR8)
- [x] **T2.5** Add streaming date-partition candidate building and full-manifest verification in `src/outage_explorer/infrastructure/parquet/candidates.py`; reuse phase 1 on bounded groups, stream-merge history, reference untouched partitions, reject duplicate keys across files/retained rows, reconcile ledgers and verify schema/hash/byte/row/exact-value round trips. Distinguish a missing incoming date partition from an entirely empty required route. Do not materialize whole history through the bounded pure API. (FR9–FR14, FR16–FR18; TR1–TR6, TR9–TR10)
- [x] **T2.6** Add real Parquet replay/merge/fault fixtures in `tests/integration/test_connector_parquet.py`: replay recorded and synthetic data, compare existing verifier results, test long/exponent decimals and representation failures, file-boundary duplicates, retention provenance, repeated refresh, all/partial exclusions and missing keys. Validate received/selected/reason counts separately from candidate/active counts. (FR6–FR14, FR16–FR18; TR1–TR6, TR8–TR10)
- [x] **T2.C** Checkpoint: run `tests/integration/test_connector_parquet.py`, existing verification suites and documented static/architecture checks; record evidence in `docs/specs/data-connector/tasks/phase-2.md`. Verify AC5 replay excluding transport sanitization, AC6–AC9 storage portions, AC10 retention decision, AC11 whole-manifest uniqueness, AC12 exact storage and AC13/AC15 reporting. These candidate-level checks do not prove durable publication or live source behavior. (AC5–AC13, AC15)


## Checkpoint evidence — 2026-10-02

`make check` passed on Python 3.14.6 with PyArrow 25.0.1: dependency consistency,
Ruff lint/format, strict mypy (39 source files), **430 tests**, and sdist/wheel
builds. The 64 phase-2 tests comprise 30 candidate integration cases in
`tests/integration/test_connector_parquet.py` and 34 cohesive evidence/schema/store
cases in `tests/integration/test_connector_evidence.py`. Existing architecture,
offline national/facility/generator, domain, health and devlog tests remain green.
The full checkpoint took 34.34 seconds for pytest; this is test duration, not a
production resource measurement.

| Acceptance portion | Verified local evidence |
| --- | --- |
| AC5 replay; AC6 exclusions; AC7 deterministic selection | Real September bundles (30 national, 1,650 facility, 2,850 generator rows) match existing verifier results, exact source strings and arithmetic. Cross-page A/B/A and later invalid rows preserve the winner; JSON types, positions, request identity and empty-page metadata survive actual Parquet. |
| AC8 replacement; AC9 retention; AC10 decision | Repeated refresh replaces valid keys without duplication; identifiable invalid rows, absent keys/entities/days and outside-interval rows retain old origins. Partial exclusions keep complete old grains; all excluded returns `retained_all_excluded`; no-prior unusable grain and entirely empty routes fail. |
| AC11 uniqueness/integrity | Cross-file duplicate keys, extra/missing partitions/references, wrong counts/hash/schema and corrupt bytes fail. Validly rehashed coherent modeled/ledger changes fail semantic replay. Pinned base manifests prevent dropping historical files or evidence dependencies. |
| AC12 exact storage | decimal128(38,12), two-decimal presentation projection, source notation, exact ratios, zero/negative values, exponent/trailing-zero and low Decimal precision cases round-trip. Otherwise-valid scale/width/projection overflow raises a representation failure. |
| AC13 coverage; AC15 accounting | Observed entity/date and usable-date counts retain gaps without fabricated zeros; page evidence preserves source totals (including facility 2,850 versus 1,650 received). Received/selected/excluded/duplicate/superseded and distinct invalid/absent/outside retention counts reconcile independently from active/candidate counts. |
| Resource/recovery scope | History larger than the per-day bound succeeds through bounded day groups and unchanged references; an overfull day and configured field/row-group/file/total/object budgets fail explicitly. Canonical immutable manifests reload through a fresh local store with no source access. Identical writes at exact budgets succeed; injected installation failures leave no partial final artifact. |

These checks verify local candidate construction and replay only. Transport
sanitization, live paging/retries, authoritative S3/RDS state, active-generation
publication, Admin authorization, supervised refresh, production limits and the
initial live load remain later phases. Independent verification currently rescans
bounded evidence by day; measure its I/O cost before production enablement.
