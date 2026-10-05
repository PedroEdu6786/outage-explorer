# Phase 6: Controlled live connector validation
> Status: complete for connector candidate/durable graph scope; backend integration deferred · Plan phase: 6 · Depends on: phase 5 checkpoint and applicable live/cloud authorization

- Scope: gather evidence with the runnable connector and implement bounded concurrency across the three independent endpoints and independent S3 object uploads/readback after measuring a sequential baseline. Fixtures/prior investigation do not prove general live guarantees. No EC2 deployment, PostgreSQL lifecycle, product activation or analytical SQL is added. Live requests/cloud writes require applicable authorization; unsupported/unrun gates stay open.
- Q1 resource measurements and Q3–Q4 paging/order/contract applicability are evidence gates, not invented production defaults. Preserve ADR-0037 initial dates and retention policies. Paths marked **new** are intended additions.

- [x] **T6.1** Create **new** `docs/specs/data-connector/live-verification.md` with a bounded procedure using the connector command with `--local-only` (Make: `LOCAL_ONLY=1`) until cloud writes are separately authorized, then record authorized small-page runs across all routes: explicit interval, safe configuration, versions, exact manifest/report references, offsets/empty termination, ties/order and source drift. Check contract applicability before extending dates; recorded order proves no revision recency and observed roster proves no upstream completeness. Facility-total diagnosis alone is not a gate. (FR4–FR8, FR14, FR15; TR4, TR6–TR8)
- [x] **T6.2** Create **new** `docs/specs/data-connector/resource-evidence.md`; measure a sequential baseline for complete-pipeline request/retry/time, arithmetic/day-group, peak memory, staging/readback disk and output costs, including repeated Parquet replay, inherited history and sequential S3 transfers under controlled behavior (live transfers only when separately authorized). Record environment, input identities, tested limits and unsupported cases. Progress from small intervals to at least 30 days and April 2–October 1, 2026 only when observed behavior/bounds support those candidate runs; synthetic caps are not production measurements. Depends on T6.1. (FR4, FR5; TR2, TR3, TR5, TR6, TR9)
- [x] **T6.2a** Implement configurable bounded endpoint concurrency in `src/outage_explorer/application/services/connector.py`, the EIA/Parquet adapters and `src/outage_explorer/bootstrap.py`; add typed configuration in `src/outage_explorer/settings.py` with sequential mode and a maximum of three endpoint workers. Execute national, facility and generator retrieval/evidence processing concurrently; allow independent per-grain modeling to overlap where measured resource bounds support it. Select/document thread or process placement from the T6.2 baseline, preserving the layered monolith and current source/model contracts. Keep pages sequential within each endpoint and assign source positions before modeling; task completion order must never determine conflict winners. A coordinator owns aggregate request/retry/time/memory/disk/output limits, progress/final reports, combined manifest creation and full graph verification. Use worker-safe transports/storage with explicit ownership/cleanup; stop admitting work and cooperatively cancel/join remaining workers on failure, interruption or resource overrun. Require all three terminal results before confirming one complete candidate; S3 final-manifest/receipt verification remains coordinated. Add **new** `tests/integration/test_connector_concurrency.py` covering actual endpoint overlap with controlled transports, reversed completion order, cross-page ties/conflicts, prior retention, shared-budget exhaustion, one-route failure, interruption and cleanup without late success. Compare sequential/concurrent exact values, source-order selection, original provenance and quality under identical recorded inputs; generated run IDs/timestamps need not match. Measure speed and aggregate peak resources against the baseline in `docs/specs/data-connector/resource-evidence.md`, and document supported concurrency/defaults without promising speedups. Controlled tests precede separately authorized live comparisons. Depends on T6.2. (FR5, FR8–FR16; TR4, TR5, TR7, TR8, TR11; AC19)
- [x] **T6.2b** Implement bounded parallel S3 dependency uploads and readback/recovery in `src/outage_explorer/application/services/connector_artifacts.py`, `src/outage_explorer/application/ports/artifacts.py`, `src/outage_explorer/infrastructure/s3/artifacts.py`, `src/outage_explorer/infrastructure/parquet/connector.py` and `src/outage_explorer/bootstrap.py`; add a separate typed S3-transfer worker setting in `src/outage_explorer/settings.py`, preserving sequential mode and measurement-supported limits. Scope is connector raw/modeled Parquet, page evidence, ledgers and manifest dependencies, not arbitrary user documents. Verify the complete local graph before scheduling uploads; upload/verify independent dependencies concurrently, then create/verify the final root manifest only after every dependency succeeds. Concurrent GETs may restore known exact dependencies after required manifest/ancestry discovery; do not discover objects by prefix listing. Full schema/value/quality/provenance/ledger replay remains a coordinated gate before a receipt. Refactor current mutable storage/transfer accounting for safe worker ownership: one aggregate deadline, attempts/wire bytes, object/graph bytes, memory and temporary/staging disk limits; concurrent workers must not multiply budgets or race duplicate/conflicting-reference checks. Preserve conditional creation, identical-content retry verification, streamed hash/byte checking, closed bodies and no overwrite/deletion. Stop admitting work on failure/interruption, cooperatively cancel/join workers and preserve earlier objects; partial completion cannot produce a verified receipt or trigger final-root creation. Keep correlated object/stage/retry/skip/failure logs secret-free and integrate this transfer setting with default candidate-to-S3 and explicit persist/recover CLI operations. Add **new** `tests/integration/test_s3_concurrency.py` with controlled overlapping PUT/GET operations, reversed completion order, identical/different existing bytes, inherited graph reconstruction, failed dependency/final manifest/readback, aggregate-budget races, interruptions and cleanup; extend `tests/integration/test_connector_artifacts.py` for default CLI behavior under parallel transfer. Compare sequential/concurrent exact references, restored values/origins/quality and receipts for the same verified local graph; measure upload/readback duration and aggregate peak resources in `docs/specs/data-connector/resource-evidence.md`, distinguishing new uploads from identical-object retries. Verify SDK client suitability and cleanup against official documentation before choosing worker placement; no new service/broker or implicit SDK multipart/transfer-manager path. Controlled checks precede separately authorized configured-bucket comparisons. Depends on T6.2a. (FR5, FR6, FR17–FR20 storage portions; TR1, TR4, TR5, TR10, TR12; AC20)
- [x] **T6.3** Update validated candidate and S3-transfer configuration in `src/outage_explorer/settings.py` and `.env.example` from measured supported ranges; extend `tests/unit/test_connector_settings.py` and `tests/integration/test_connector_cli.py` for changed limit behavior. Preserve explicit caller budgets and fail-closed overruns; record unproven process-level enforcement in `docs/specs/data-connector/resource-evidence.md` as a deferred backend gate, without an EC2/supervision prerequisite. Depends on T6.2b. (FR5; TR4–TR6)
- [x] **T6.4** Record candidate rerun/recovery observations in `docs/specs/data-connector/live-verification.md` and `docs/specs/data-connector/recovery-verification.md` using explicit prior manifests and source-disabled replay. Extend `tests/integration/test_connector_reruns.py` only for newly observed regression cases; exercise absent/invalid/partial/all-excluded behavior through controlled inputs when live data cannot produce it. Distinguish live evidence from injected failures; verify usable output in all grains for the initial-interval candidate without calling it product publication. Depends on T6.3. (FR5, FR9–FR16, FR18 candidate portion; TR2–TR9)
- [x] **T6.5** Perform separately authorized configured-bucket persistence/readback and reconstruction in empty local staging with EIA disabled; record sequential/concurrent upload/readback/reconstruction observations and actual SDK/AWS evidence, exact nonsecret durable references, inherited-dependency verification and unrun gates in `docs/specs/data-connector/recovery-verification.md` and `docs/specs/data-connector/aws-setup.md`. Reuse default candidate-to-S3 or explicit phase-5 persistence/recovery commands; do not delete authoritative inputs, change infrastructure or imply backend outcomes are durable. Depends on T6.4. (FR6, FR17–FR20 storage portions; TR1, TR4, TR5, TR10)
- [x] **T6.6** Update usage, measured limits and implementation status in `README.md`, `docs/context/code-structure.md`, `docs/context/architecture.md` and `docs/specs/data-connector/plan.md`; annotate `docs/specs/data-connector/spec.md` acceptance with actual evidence and deferred backend portions. Keep incomplete ACs unchecked, preserve historical ADRs and distinguish Python/PyArrow processing from unimplemented DuckDB execution. Depends on T6.5. (FR4–FR20 connector portions; TR1–TR10)
- [x] **T6.C** Checkpoint: run documented `make check` from `README.md` after implementation changes; validate evidence references and verify bounded endpoint and S3-transfer concurrency/equivalence and record sequential/concurrent measurements, local/live/cloud checks and unmet gates in `docs/specs/data-connector/tasks/phase-6.md`. Reconcile AC3 live paging, AC4 measured bounds, AC5–AC15 candidate evidence and AC17–AC18 storage recovery. Complete this phase only for demonstrated connector behavior; carry AC1–AC2, AC16 and remaining authorization/publication/operational-recovery portions to the later backend breakdown. No production enablement follows automatically. Depends on T6.6. (AC3–AC15, AC17–AC20; TR1–TR12)


## Execution checkpoint — October 4, 2026

- T6.1/T6.2: bounded live one-day and September candidates, controlled 30-day
  sequential baseline and sequential/concurrent transfer measurements recorded.
- T6.2a/T6.2b/T6.3: optional independent 1–3 worker configuration, aggregate
  admission/accounting, cancellation/join, deterministic coordinated models,
  dependency-before-root ordering and exact replay implemented. Sequential defaults
  remain. Logical memory/staging envelopes are not hard process guarantees.
- T6.5: separately user-authorized configured-bucket one-day and inherited-graph
  persistence/readback and EIA-disabled empty-staging recovery passed. Dependency
  sequencing did not imply initial-interval completion; this independent storage
  proof uses smaller verified candidates. Objects/infrastructure were preserved.
- T6.6: usage/status/spec annotations and concrete measured/unmet gates synchronized.
- T6.4 remains incomplete: exact-prior live rerun and controlled retention cases
  passed, but April 2–October 1 did not produce a confirmed verified candidate.
  Its retry retrieved 183/10,065/17,385 observations, took 564.433 seconds and was
  interrupted during verification after exceeding the selected 300-second budget.
  Source/artifact partials are preserved. Cooperative checks were subsequently
  added at storage/batch boundaries to stop delayed deadline observation.
- T6.C remains open: initial-interval verified usable output/contract applicability
  is unsupported. AC3/AC5–AC15 and AC17–AC20 have the documented controlled,
  bounded live and storage evidence; incomplete backend and initial portions remain
  open. No production enablement follows.
- An intermediate `make check` passed dependency checks, Ruff lint/format, strict
  mypy (59 source files), 849 tests and sdist/wheel builds. Final checks after
  cooperative-check/additional-test changes are reported below when completed.

Final checkpoint after cancellation, retention and CLI changes: `make check`
passed dependency checks, Ruff lint, Ruff format (208 files), strict mypy
(67 source files), **879 tests passed / 22 skipped** out of 901 collected, and
sdist/wheel builds. Skips belong to concurrent user-access/PostgreSQL integration
work and do not substitute for connector verification. All connector concurrency,
artifact, source, rerun and architecture suites ran successfully. Evidence links
and `git diff --check` passed. T6.C remains unchecked solely because the measured
initial-interval complete-candidate gate is open, not because these local checks failed.

- [x] **T6.7** User-directed page-fetch extension: implement ADR-0049/TR13/AC21
  bounded concurrent page windows, canonical received-count repair, audited
  lookahead graph dependencies, aggregate nested-worker bounds/cancel/join and
  simple fetch/S3 CLI/Make overrides. Preserve existing defaults and endpoint
  compatibility. Controlled overlap/reverse/short/empty/totals/budgets/faults/
  interruption/recovery/override checks and final `make check` are required.
  Do not run the full live183-day candidate or close T6.4/T6.C by this extension.


### Page-fetch extension checkpoint (T6.7 / AC21)

Completed controlled verification of actual overlapping page requests within one
route, reversed completion/cross-page conflict equivalence, short-page offset
repair, audited unused successes/one canonical terminal, misleading facility
totals, exact supplemental S3 recovery, retained original origins, fetched-row
budget exhaustion, admitted lookahead failures/interruption, nested worker join,
credential scans and rehashed inconsistent-audit rejection. CLI/Make worker
validation/precedence and independent S3 overlap suites passed. No full initial
live candidate was run or newly verified.

Final `make check` passed pip dependency checks, Ruff lint/format (226 files),
strict mypy (76 source files), **1,108 passed / 25 skipped** of1,133 collected
in120.46 seconds, and sdist/wheel builds. Skips belong to current user-access/
PostgreSQL checks. Diff whitespace and the plain Make command dry run passed.
T6.4/T6.C remain open for full initial verification; page parallelism does not
parallelize synchronous modeling/replay or establish production/snapshot guarantees.

- [x] **T6.8** Correct comparison-stage repeated replay with bounded day indexes,
  including retained history; expose grain/day progress. Measure183-day controlled
  old/new replay counts and elapsed time, reproduce from retained local source
  evidence without EIA/AWS, regress integrity/retention/budgets and run make check.


### Comparison-stall correction checkpoint (T6.8)

Fresh replay-derived day staging replaces per-day source scans, including original
retained-history binding; full raw/value/origin/quality/ledger/ancestry checks
remain. Controlled183-day verification measured552 versus3 day-index replays
and8.810 versus1.808 seconds. Captured full-interval live inputs replayed locally
with sources/AWS disabled:20.995 seconds build+verify,11.075 seconds fresh verify,
all183/10065/17385 selected and183 usable dates per grain. Thus captured initial
input usability is now demonstrated; fresh live CLI/default-durable receipt
completion still remains unrun, so T6.4/T6.C retain the end-to-end gate.

Final make check passed dependency checks, Ruff lint/format228files, strict mypy
76sources, **1112 passed /25 skipped** of1137collected in82.42seconds, and
sdist/wheel builds. Focused integrity/retention/page/S3/budget cases passed;
recovery exact-local-object assertions now include only fresh derived raw day
partitions outside the durable graph. Global injected write/link failures occur
during prior verification and remain fail-closed as prior_integrity. Temporary
atomic files are cleaned and prior artifacts remain readable. No live source or
AWS request/write was made for this correction.

## Final phase closure after the completed live rerun

The earlier open-gate checkpoints above remain historical. Fresh live run
`de9648fcb92149a98d66aba51e4f667f` completed the entire initial interval and
verified183/10,065/17,385 selected observations with183 usable dates in all grains.
GET-only configured-S3 recovery with EIA disabled,3 S3 workers and fresh staging
verified exact manifest
`f74027258fdbf78ba040128b4761166c15249177365df4eba7db1bd5f5232cd0:563052`,
2054objects/63,420,955bytes and every semantic invariant. Recovered summaries
exactly equal the local live report. Recovery93.154seconds; peakRSS154,238,976bytes;
staging2857objects/80,516,102bytes. Recorded in
[closure measurement](../evidence/2026-10-04/initial-interval-recovery.json).
T6.4/T6.C are now complete; all11 phase6 tasks and54 six-phase connector tasks
are checked. Source/model AC3/AC5–AC9/AC12–AC15 and controlled AC19–AC21 have
actual evidence. Backend-containing AC1/AC2/AC4/AC10/AC11/AC16–AC18 stay unchecked.

Last code checkpoint remains `make check`:1112 passed/25 skipped in82.42seconds,
Ruff lint/format228files, strict mypy76sources and package builds passed. This
closure changes documentation/evidence only; no redundant full-suite run was
needed. Exact CLI recovery and documentation task/reference checks ran for closure.
No product publication, deployment, commit or push follows automatically.
