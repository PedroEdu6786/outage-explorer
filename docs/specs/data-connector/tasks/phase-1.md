# Phase 1: Pure merge, provenance and accounting
> Status: complete · Plan phase: 1 (independent foundation) · Depends on: none

- [x] **T1.1** Add immutable origin references, modeled rows, explicit inclusive interval, caller-supplied row/field/arithmetic bounds and pure result/error types in `src/outage_explorer/domain/refresh.py`; references preserve run/retrieval/request/page/source position and contract/transformation/evidence identity without performing I/O. Keep current merge decisions separate from origin provenance. (FR6, FR10; TR4, TR5, TR6)
- [x] **T1.2** Add bounded per-grain modeling in `src/outage_explorer/domain/refresh.py` using existing `assess`, `select_daily` and `calculate`: preserve global source positions and source strings, validate before selection, reject duplicate positions and preflight coefficient/exponent complexity before rational expansion. Accept bounded groups or explicit caps; resource/interval/input-integrity failures are separate from row exclusions. Do not call the September-only `VerifyBaseline`. (FR5, FR7, FR8, FR13; TR2, TR3, TR5, TR8)
- [x] **T1.3** Add bounded pure merge in `src/outage_explorer/domain/refresh.py`: replace existing keys with valid winners, retain matching old valid rows for trustworthy excluded keys without a winner and retain absent prior in-window keys separately, preserve origin exactly, distinguish unchanged outside-interval rows, and reject duplicate prior/output keys. Unmatched invalid rows never acquire guessed identities. This API operates on a bounded partition, not accumulated history. (FR9, FR10, FR12; TR4, TR6, TR10)
- [x] **T1.4** Add complete-three-grain policy inputs in `src/outage_explorer/domain/refresh.py`: distinguish nonempty all-excluded input, partial-all-excluded routes, absent prior in-window keys and an empty required route. Apply confirmed ADR-0037 policies: preserve the complete prior route when only that route is all-excluded, retain all active data without publication when all routes are excluded, and require usable incoming rows in every grain for initial loading. Distinguish initial loading from a complete existing generation and reject incomplete prior generations. Expose pure transformation eligibility without granting publication rights. Keep candidate counts distinct from unchanged active counts and make no publication claim. (FR11, FR18; TR6, TR9, TR10)
- [x] **T1.5** Add per-grain quality accounting in `src/outage_explorer/domain/refresh.py`: reconcile received = selected + excluded + duplicate + superseded, count reason occurrences separately, count distinct retained-old keys once, and reconcile modeled = selected + retained-invalid + retained-absent + carried-outside-interval. Preserve grain independence and distinguish observed/usable coverage from requested dates without zero filling or upstream-completeness claims. (FR13, FR14, FR16; TR3, TR4)
- [x] **T1.6** Add behavior tests in `tests/unit/test_refresh.py` for arbitrary dates, all three natural keys, cross-page-position A/B/A and equivalent decimals, facility-name changes, late invalid rows, repeated refresh, valid replacement, original provenance retention, unknown keys, absent-key retention, partial/all-excluded retention, initial-load eligibility, incomplete prior generations, empty sources, duplicate keys, independent national arithmetic, exact/half-up values, multi-reason accounting and each explicit input/arithmetic bound. Use independently calculated expectations; synthetic caps are not production measurements. (FR7–FR14, FR16, FR18; TR2–TR6, TR8–TR10)
- [x] **T1.C** Checkpoint: run the documented Ruff, mypy and pytest checks from `README.md`, including `tests/unit/test_refresh.py`, existing national/detail verification regressions and `tests/architecture/test_import_boundaries.py`; record results and phase status in `docs/specs/data-connector/tasks/phase-1.md`. Verify only pure portions of AC6–AC10, AC11 key rejection, AC12 arithmetic/grain independence, AC13 coverage and AC15 counts. AC5 durable replay, AC8–AC12 storage/publication, all live/resource measurements and all active-generation guarantees remain pending. (AC6–AC13, AC15)

## Checkpoint evidence — 2026-10-02

- Implemented T1.1–T1.6 and passed T1.C. `make check` passed dependency consistency,
  Ruff lint/format, strict mypy, all **366 pytest tests** (including **52 new refresh
  tests**, existing national/detail regressions and architecture checks), and
  source/wheel builds on local Python 3.14.6. No remote CI run is claimed.
- Verified pure AC6–AC9 behavior, AC10 all-excluded retention facts, AC11 local
  duplicate-key rejection, AC12 independent exact arithmetic in all three grains,
  AC13 observed/usable coverage and AC15 disposition/reason/retention accounting.
  These are the unit-level portions only; spec acceptance checkboxes remain open.
- Source-position selection preserves page/request/evidence references and source
  numeric strings. Input is assumed sanitized upstream. Inputs, fields, source
  indices, arithmetic complexity, reason occurrences and output rows have explicit
  caller caps; iterator overflow stops after the first row beyond its cap. These
  synthetic test budgets are not production resource measurements.
- The API accepts a complete bounded route group. Empty route input fails; future
  streaming orchestration must separately handle absent date partitions within a
  nonempty route. This is not an accumulated-history merge implementation.
- Confirmed ADR-0037 absence and partial-exclusion policies are implemented:
  absent prior keys remain in the candidate with original provenance and distinct
  retention counts; an all-excluded route retains its complete prior rows while
  other routes may update. All-excluded refreshes retain the existing generation
  without publication. Initial loading requires usable rows in every route and
  cannot masquerade as retention; incomplete prior generations fail. Pure
  transformation eligibility does not grant publication rights. Current active
  counts remain separate from candidate counts. Nothing is published.
- Durable raw replay, cross-file uniqueness, storage/schema round trips, retrieval,
  sanitization, authorization, publication, active-generation guarantees and live
  measurements remain pending later phases.

Next step: Review the diff, then run /implement for phase 2.
