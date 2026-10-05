# Tasks: Docker analytical runtime

> Status: Phase 1 implemented and controlled checkpoint passed; Phases 2–5 pending · Slug: analytical-runtime · Plan: [plan.md](plan.md) · Spec: [spec.md](spec.md)

The original task list was planning-only; Phase 1 implementation was explicitly
authorized on October 5, 2026. Existing
[data-api phases](../data-api/tasks.md) are reused rather than reset. Proposed
new files/test commands do not exist until their tasks deliver them. Keep phases
sequential; checkpoint evidence is required before moving to dependent work.
This document itself grants no Docker execution, enablement, deployment or
publication authorization. T1.7 remains owned by the user.

## Phase 1: Runtime profile and strict transport

- [x] **T1.1** Define inert typed candidate/reviewed profile and evidence contracts
  in proposed `src/outage_explorer/infrastructure/worker_runtime/configuration.py`
  and `src/outage_explorer/settings.py`; specify finite bounds, explicit local
  Docker daemon/image identity, strict mount/env policy, profile invalidation and
  unreviewed/unstarted fail-closed states. Record unresolved budgets in `plan.md`.
  (FR3, FR9, FR11, TR2–TR6)
- [x] **T1.2** Add strict response/request serialization adapter in proposed
  `src/outage_explorer/infrastructure/worker_runtime/decoding.py`, reusing
  `protocol.py` and `query_results/encoding.py`; reject duplicates, unknown keys,
  versions/operations, invalid descriptors/cells/counts/limits/keys and excessive
  expansion; reconstruct preview date/Decimal values and exact query document
  bytes. Use existing safe application errors. Depends on T1.1. (FR3, FR6–FR8)
- [x] **T1.3** Make worker engine limits match validated nonsecret runtime profile
  in `src/outage_explorer/bootstrap.py` and
  `src/outage_explorer/entrypoints/query_worker_startup.py`; preserve internal v1
  and public caps, reject mismatched/out-of-policy values. Document candidate
  profile in `infrastructure/analytical-worker/README.md`. Depends on T1.1–T1.2.
  (FR3, TR2–TR4)
- [x] **T1.C** Add proposed `tests/unit/test_worker_response_decoding.py` and
  `tests/unit/test_analytical_runtime_configuration.py`; run controlled protocol,
  canonical encoding and architecture regression plus Ruff/mypy. Include actual
  date/Decimal round trips, duplicate labels/nested types, exact canonical result
  field order/bytes and exit/error mismatch. No Docker required. Depends on
  T1.1–T1.3. Gate: AC3 and configured bounds contract proved; readiness still
  absent. (AC3, TR5–TR6)

### Phase 1 checkpoint evidence (October 5, 2026)

AC3 and the configured bounds contract passed controlled verification: 217 tests
in response decoding, configuration, existing protocol/encoding, architecture and
real-worker-subprocess suites. Real DuckDB returned date/Decimal/nested cells and
duplicate labels with exact retained bytes; real Parquet preview reconstructed
date/Decimal values. Ruff lint/format and mypy passed. No Docker was executed;
readiness, AC2/AC4/AC7 and original data-api T1.7 remain open. A broader pytest
attempt was interrupted after 202 passed/19 skipped/9 fixture errors because
`OUTAGE_TEST_POSTGRES_DSN` was not configured; it is not a full-suite pass.

## Phase 2: Inputs, Docker lifecycle and recoverable ownership

- [ ] **T2.1** Implement bounded private copy/verify/atomic staging in proposed
  `src/outage_explorer/infrastructure/worker_runtime/inputs.py`, adapting
  `src/outage_explorer/infrastructure/local_cache/modeled.py` only as needed for
  owned teardown. Reject symlink/nonregular/replacement races; bind exact staged
  digest files read-only, enforce independent bytes/files/deadlines, test UID
  readability without cache/raw siblings. Depends on T1.C. (FR1–FR2, FR12, TR2)
- [ ] **T2.2** Implement bounded Docker control and `ReviewedRuntime` in proposed
  `src/outage_explorer/infrastructure/worker_runtime/docker.py`; structured
  create/start/attach, concurrent bounded I/O, minimal environment, strict local
  daemon, immutable image, isolation flags, all deadlines, cancellation,
  kill/wait/inspect/remove and safe mapping. Track ambiguous creation and do not
  release slot/files on uncertain liveness. Depends on T2.1. (FR3–FR6, TR2–TR3)
- [ ] **T2.3** Add explicit recovery-lease handoff to
  `src/outage_explorer/application/ports/execution.py`,
  `src/outage_explorer/application/services/queries.py` and `preview.py`; create
  proposed `src/outage_explorer/infrastructure/worker_runtime/ownership.py` for
  strong lease retention, bounded private ledger/owner locks and controlled
  reconciliation. Preserve authorization ordering and keep orchestration in
  application ports; retain SQL pins/reservations or preview active lease on
  failed reaping without relying on garbage collection. Depends on T2.2.
  (FR1, FR4–FR5, FR9–FR12)
- [ ] **T2.C** Add proposed `tests/unit/test_docker_runtime.py` and
  `tests/integration/test_analytical_input_staging.py`; extend
  `tests/integration/test_query_lifecycle.py` and `test_catalog_preview.py` for
  failed reap/retry, expiry with active preview lease, no release/download on
  busy, control subprocess failure/oversized streams, ambiguous create/start,
  crash/OOM/cancel/timeouts and death-vs-removal distinction. Run existing
  lifecycle suites and static/architecture checks. Depends on T2.1–T2.3.
  Gate: controlled AC1–AC4 hold; no real isolation claim. (AC1–AC4)

## Phase 3: Explicit composition and local supervision

- [ ] **T3.1** Build inert forwarding resources in `src/outage_explorer/bootstrap.py`
  and proposed `src/outage_explorer/infrastructure/worker_runtime/supervisor.py`;
  explicitly construct `VerifiedModeledCache` during start, connect trusted S3
  reads, launcher, encoding, preview sequences, result lifecycle and bounded
  cleanup/recovery. Validate matching readiness record before accepting work;
  start failure rolls back owned resources. Depends on T2.C. (FR9–FR12, TR5)
- [ ] **T3.2** Integrate autonomous preview expiry/active-lease cleanup in
  `src/outage_explorer/infrastructure/query_results/previews.py` and result
  lifecycle in `cleanup.py`; reconcile private owner containers before removing
  their staging/cache, preserve live readers and unresolved workers, and keep
  refresh independent. Depends on T3.1. (FR4–FR5, FR10, FR12)
- [ ] **T3.3** Deliver proposed
  `src/outage_explorer/entrypoints/http/analytical_startup.py`, with corresponding
  exact startup exception coverage in `tests/architecture/test_import_boundaries.py`;
  define `--config` for a nonsecret profile, explicit supervisor start/close and
  rejected reloader/fork/multi-serving-process modes. Update `README.md` and
  `infrastructure/analytical-worker/README.md`. Depends on T3.1–T3.2.
  (FR9–FR11, TR1, TR5)
- [ ] **T3.C** Add proposed `tests/integration/test_analytical_supervisor.py`, extend
  `tests/integration/test_data_api_http.py` and
  `tests/acceptance/test_data_api_lifecycle.py`; prove inert import/factory,
  start/rollback/repeated-close/process ownership, dead-owner reconciliation,
  fail-closed missing evidence, restart lost IDs, old snapshots across publication,
  zero new worker on GET pagination, current-role denial and healthy independent
  refresh. Run documented checks. Depends on T3.1–T3.3. Gate: controlled AC5–AC6
  hold; no API enablement. (AC1, AC5–AC6)

## Phase 4: User-owned runtime evidence and readiness

- [ ] **T4.1** Deliver proposed `tests/acceptance/test_query_runtime.py` with explicit
  `runtime_docker`/`runtime_measurements` pytest markers registered in
  `pyproject.toml`, documented opt-in/profile/image prerequisites and synthetic
  denied-access canaries. Default suite skips real-runtime tests unless explicitly
  selected/configured. Include namespace/network/mount/env, resource quota,
  child survival, stalled I/O/control failures and cleanup probes. Make report
  bounded and secret-free. Depends on T3.C. (AC2, AC4, AC7, TR6)
- [ ] **T4.2** Document concrete representative-data/overlap setup and measurement
  invocation in `infrastructure/analytical-worker/README.md`; parameterize the
  harness with a nonsecret profile and verified representative public inputs,
  cold/warm cache runs, encoding/spool/index work, retained old snapshot,
  concurrent refresh/query/API workload, peak process/container/host memory,
  disk, transfer and latency evidence. Do not initiate source refresh/publication
  merely to benchmark. Depends on T4.1. (TR3, TR6, AC7)
- [ ] **T4.3 — USER-OWNED** Execute the checklist below only after explicit user
  direction. Record actual commands/platform/image/results/failures and review
  budgets in `docs/specs/data-api/runtime-evidence.md`. Keep
  `docs/specs/data-api/tasks/phase-1.md` T1.7/T1.C open until their full evidence
  exists. Depends on T4.1–T4.2. (AC2, AC4, AC7)
- [ ] **T4.C** Review the complete matching readiness record, isolation/termination
  evidence, storage enforcement and representative budgets; resolve plan open
  decisions. Record failed/skipped gates explicitly and invalidate stale evidence.
  Depends on T4.3. Gate: AC7 passes; deployment/publication/API enablement still
  require their own explicit authorization. (FR11, TR6, AC7)

### T1.7 runnable local checklist (not executed)

Commands below are a **future delivered interface**, runnable after T4.1/T4.2;
`tests/acceptance/test_query_runtime.py` and its options currently do not exist.
The harness must document `OUTAGE_RUNTIME_TEST_PROFILE` as a path to the
nonsecret reviewed/candidate profile, not a credentials file. Run from repository
root; keep shell tracing off. Do not dump `env`, Docker inspection environment,
request bodies, real credentials, `.env` or session values into evidence.

1. Confirm explicit user direction; prepare synthetic public projections and
   fake credential canaries, plus independently approved representative inputs.
   Keep the profile distinct from host auth/database configuration.
2. Record local platform and daemon version without inspecting credentials:

   ```sh
   uname -s
   docker version --format '{{.Server.Version}} {{.Server.Os}} {{.Server.Arch}}'
   docker build -f infrastructure/analytical-worker/Dockerfile -t outage-analytical-worker:validation .
   docker image inspect --format '{{.Id}}' outage-analytical-worker:validation
   ```

3. Set the profile's exact image identity and run the delivered isolation and
   lifecycle harness (one serving process; supported quota storage required):

   ```sh
   OUTAGE_RUNTIME_TEST_PROFILE=/private/tmp/outage-runtime-profile.json \
     .venv/bin/python -m pytest -q tests/acceptance/test_query_runtime.py -m runtime_docker
   ```

   Require denied read/write to cache siblings/raw/repository/credentials, denied
   network and Docker socket access, UID/capabilities/root/temp policy checks,
   memory/CPU/process/temp enforcement, timeout ≤10-second execution plus bounded
   termination, no surviving descendants, container removal and safe failure.
   Deliberately failed reap must preserve slot/pins through expiry and recover
   only after proven death. Test daemon unavailable/ambiguous create/restart.
4. Run delivered measured workload profile; no automatic source rerun or publication:

   ```sh
   OUTAGE_RUNTIME_TEST_PROFILE=/private/tmp/outage-runtime-profile.json \
     .venv/bin/python -m pytest -q tests/acceptance/test_query_runtime.py -m runtime_measurements
   ```

   Record cold/warm and overlap workload identity, cache/staging/spill/spool/index
   high-water marks, host/container memory, CPU, bytes transferred and latency;
   compare all preparation/overall/control/output bounds and API responsiveness.
   Tmpfs-only smoke cannot establish ADR-0007 disk-spill enforcement.
5. Review sanitized reports, set measured budgets, rerun affected gates for changed
   profiles and record user approval/evidence identity. Missing coverage keeps
   readiness closed. Do not tick original T1.7 merely for `SELECT 42` success.

## Phase 5: Separately authorized local API acceptance

- [ ] **T5.1** After T4.C and explicit API-enablement direction, start the delivered
  supervisor using a matching reviewed profile. Confirm previously configured
  trusted auth/PostgreSQL/S3 access without reading/logging secrets; do not deploy
  or publish. Record safe health/catalog/readiness outcomes. Update
  `docs/specs/data-api/runtime-evidence.md`. (FR9, FR11, AC6–AC7)
- [ ] **T5.2** Perform preview and SQL checks below through curl or Postman, then
  current-role/cursor/query expiry and overlap/busy checks using safe controlled
  setup. GET paging must make zero worker calls. Validate failure rollback returns
  analytical execution to 503 while independent catalog/refresh remain available.
  Record evidence in `docs/specs/data-api/runtime-evidence.md`. Depends on T5.1.
  (AC1, AC5–AC6)
- [ ] **T5.C** Verify complete AC1–AC7 traceability, report remaining environment/
  deployment gaps, run documented relevant regression/static/package checks and
  append devlog evidence. Never infer EC2 readiness from local results.
  Depends on T5.1–T5.2. (AC1–AC7)

### Future local startup and HTTP checks

The proposed command below is **unavailable until T3.3 implements it**. This
planning change does not run it or change any enablement settings:

```sh
.venv/bin/python -m outage_explorer.entrypoints.http.analytical_startup \
  --config /private/tmp/outage-runtime-reviewed.json
```

Use the already authenticated browser/Postman cookie jar and permitted Origin;
never print/export session/CSRF values into evidence. In Postman use the existing
private cookie jar and secret/private variable for `X-CSRF-Token`, with query
parameters in the URL and only `sql` in the JSON body. Save no secret-bearing
collection exports. The [auth contract](../user-access/http-contract.md) governs
login/session acquisition; do not invent a token header.

Curl example uses an existing private curl configuration file containing local
URL, cookie and Origin/CSRF transport settings; its creation remains governed by
existing auth procedures. Do not display its contents, use `-v`/`--trace`, or place
secret literal values on the command line. `base_url` below is nonsecret.

```sh
base_url=http://127.0.0.1:5000
curl --config /private/tmp/outage-api-private.curl --silent --show-error \
  "$base_url/api/datasets"
curl --config /private/tmp/outage-api-private.curl --silent --show-error \
  "$base_url/api/datasets/national/preview?page_size=2"
curl --config /private/tmp/outage-api-private.curl --silent --show-error \
  --get --data-urlencode "cursor=$preview_cursor" \
  "$base_url/api/datasets/national/preview"
curl --config /private/tmp/outage-api-private.curl --silent --show-error \
  --header 'Content-Type: application/json' \
  --data '{"sql":"SELECT period FROM national ORDER BY period LIMIT 5"}' \
  "$base_url/api/query?page=1&page_size=2"
curl --config /private/tmp/outage-api-private.curl --silent --show-error \
  --get --data-urlencode "query_id=$query_id" --data-urlencode 'page=2' \
  "$base_url/api/query"
```

Select the dataset ID/SQL name from the actual catalog: the examples use the
existing national relation name; set `preview_cursor` and `query_id` from the
prior response in private local client state. Cursor continuation supplies no
replacement filters/page size. Page 2/revisited page 1 must preserve the same
query ID, generation, columns and row sequence; compare all three pages with the
one five-row retained result. A reference-free `SELECT 42 AS answer` is a useful
transport check but does not replace published-input preview/SQL acceptance.
Use current application-role tests and independently authorized refresh overlap
without adding a refresh POST to this checklist.
