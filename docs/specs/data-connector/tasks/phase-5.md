# Phase 5: Durable connector artifacts in S3
> Status: complete (controlled SDK checkpoint, 2026-10-04) · Plan phase: 5 · Depends on: phase 4 checkpoint

- Scope: persist/recover the complete verified graph by immutable exact reference; this does not activate a backend generation or persist PostgreSQL refresh outcomes. Controlled SDK tests precede separately authorized AWS checks. No authoritative-data deletion is introduced.
- Paths marked **new** are intended additions; paths introduced in phase 4 must exist before this phase starts.

- [x] **T5.1** Select/pin the S3 SDK in `pyproject.toml` and `requirements-dev.txt`; record official conditional-write/readback behavior, compatibility and bounded retry/timeout choices in `docs/specs/data-connector/plan.md`. PostgreSQL tooling and DuckDB remain outside this task. (TR1, TR5)
- [x] **T5.2** Extend storage contracts in `src/outage_explorer/application/ports/artifacts.py` and graph/result contracts in `src/outage_explorer/application/ports/connector.py`; express exact references, bounded graph transfer and verified durable receipts without SDK types, arbitrary caller URLs or active-pointer semantics. Preserve local-candidate contracts. Depends on T5.1. (FR6, FR17–FR20 storage portions; TR1, TR4, TR5, TR10)
- [x] **T5.3** Create **new** `src/outage_explorer/infrastructure/s3/__init__.py` and **new** `src/outage_explorer/infrastructure/s3/artifacts.py`; implement configured bucket/prefix, application-generated keys, conditional create, identical-content retry verification and bounded streamed readback. Check SHA-256/byte counts rather than treating ETag as a content hash; reject different existing bytes, truncated/missing objects, exhausted retries and hash mismatch without overwriting earlier objects. Depends on T5.1–T5.2. (FR6, FR17–FR20 storage portions; TR1, TR4, TR5, TR10)
- [x] **T5.4** Add bounded graph export/restoration to `src/outage_explorer/infrastructure/parquet/connector.py`, reusing `src/outage_explorer/infrastructure/parquet/manifests.py` validation; enumerate exact references including base manifests, inherited raw/page evidence and unchanged modeled dependencies, without prefix-listing discovery. Restore into fresh staging, then verify schemas/counts/exact values/ledgers/full replay; reject incomplete/conflicting dependencies and graph limits. Depends on T5.2. (FR6, FR12, FR17–FR20 storage portions; TR1–TR5, TR10)
- [x] **T5.5** Create persistence/recovery use cases in **new** `src/outage_explorer/application/services/connector_artifacts.py`; verify the local candidate, transfer its complete graph through ports, verify readback and persist/verify the final manifest after dependencies. Return a durable reference only after full verification; recover by exact reference with EIA disabled. Failures preserve prior objects; retries cannot turn incomplete upload into success or publication. Depends on T5.3–T5.4. (FR6, FR17–FR20 storage portions; TR1, TR4, TR5, TR10)
- [x] **T5.6** Add explicit persist/recover operations in `src/outage_explorer/entrypoints/cli/connector.py`, composition in `src/outage_explorer/bootstrap.py` and S3 configuration in `src/outage_explorer/settings.py` and `.env.example`; use the configured bucket/prefix and injected credential provider without exposing secrets. Local candidate operation remains AWS-independent. Update `tests/integration/test_startup.py` if composition changes. Depends on T5.5. (FR6, FR18, FR20 storage portions; TR1, TR4, TR5)
- [x] **T5.7** Add controlled SDK fault tests in **new** `tests/integration/test_s3_artifacts.py`; verify conditional creation, identical/different existing bytes, retry/deadline/byte caps, partial upload, missing/corrupt/truncated readback and secret-free diagnostics. Assert no overwrite/deletion or verified receipt after incomplete verification; distinguish stubs from AWS evidence. Depends on T5.3. (FR17–FR20 storage portions; TR1, TR4, TR5, TR10)
- [x] **T5.8** Add persistence/recovery integration in **new** `tests/integration/test_connector_artifacts.py`; reconstruct real Parquet in empty staging through the CLI and controlled S3 adapter with EIA disabled, including a candidate retaining earlier evidence. Compare exact values/origins/quality and retry behavior; inject dependency upload/readback and final-manifest failures. Depends on T5.6–T5.7. (FR6, FR12, FR17–FR20 storage portions; TR1–TR5, TR10)
- [x] **T5.9** Document persist/recover commands in `README.md` and controlled-versus-AWS verification in **new** `docs/specs/data-connector/recovery-verification.md` and `docs/specs/data-connector/aws-setup.md`; identify inherited dependencies and remaining product guarantees. Define separately authorized configured-bucket checks for phase 6 without claiming they ran or adding provisioning/retention policies. Depends on T5.8. (FR17–FR20 storage portions; TR1, TR4, TR10)
- [x] **T5.C** Checkpoint: run `make check` from `README.md`, including `tests/integration/test_s3_artifacts.py`, `tests/integration/test_connector_artifacts.py` and phase-4 regressions; record evidence in `docs/specs/data-connector/tasks/phase-5.md`. Verify AC5 durable-graph replay and AC17–AC18 artifact integrity/recovery under controlled SDK behavior. AWS checks, active publication, reader pinning, uncertain PostgreSQL commits and recovery of refresh outcomes remain separate; do not claim full AC16–AC18 completion. Depends on T5.9. (AC5, AC17, AC18; TR1, TR4, TR5, TR10)


## Recorded checkpoint — 2026-10-04

T5.1–T5.9 and T5.C completed. Final-code `make check` passed on Python 3.14.6:

- Dependency validation: no broken requirements.
- Ruff lint and format: passed (171 files formatted).
- Strict mypy: passed (55 source files).
- Pytest: **807 passed in 65.98 seconds**, no failures or skips. The new
  controlled SDK and durable graph suites contribute **43 tests** (22 S3,
  21 persistence/recovery). Phase-4 CLI/rerun/configuration/service tests,
  startup/import-boundary negative fixtures and source/Parquet/verifier/health/
  devlog regressions are included.
- Wheel and source distribution built with `--no-isolation`. Wheel contents
  include the new S3/service adapters and pinned Boto3 dependency metadata.
- Installed module help and local documentation links passed. `git diff --check`
  passed. No commits, pushes, live EIA requests, configured AWS calls/writes,
  database writes, provisioning or publication were performed.
- Two earlier full runs passed 805 tests before the final deadline tests. After
  the final full run began, the retained-recovery fixture was strengthened to
  exercise cross-page A/B/A in all grains and compare inherited replay directly;
  that final focused test passed separately (1 test in 4.16 seconds).

| Criteria | Controlled durable-artifact evidence |
| --- | --- |
| AC5 | Complete graph recovery into empty staging with EIA disabled; source strings, cross-page A/B/A positions/order and request/retrieval origins, modeled exact values, retained origins and quality compare with the original. Sanitized evidence stays secret-free after S3 transfer. |
| AC17 artifact portion | Conditional creates, verified identical retries, conflicting/partial bytes, exhausted retries, byte/graph/deadline limits, missing/truncated/corrupt readback and dependency/final-manifest/full-replay faults reject unconfirmed success. Prior objects are preserved; no overwrite, listing or deletion is exposed. Late PUT/GET responses cannot bypass deadlines and stream bodies close. |
| AC18 artifact portion | Exact root references reconstruct ancestor manifests, inherited raw/page evidence and unchanged modeled dependencies into fresh real-Parquet staging without EIA or operational PostgreSQL. Receipt requires fresh full schema/count/value/ledger/replay verification. |

`aws-setup.md` already contained historical setup evidence despite its task's
"new" label; it was extended while preserving those observations. They do not
prove this adapter's configured-bucket behavior. Official SDK contracts and
initial bounded retry/timeout choices are recorded in the plan.

Full AC16–AC18 remain open: configured-bucket/deployed-role checks, active
publication, reader pinning, uncertain PostgreSQL commits and recovery of durable
refresh outcomes are separate. Resource defaults remain unmeasured initial
limits. Interrupted transfer/recovery may leave unconfirmed objects/staging;
retry persistence verifies existing bytes, while failed recovery needs fresh
staging. No authoritative retention/deletion policy was introduced.

Next: Review the diff, then run /implement for phase 6, with its applicable
live/cloud authorization resolved separately.
