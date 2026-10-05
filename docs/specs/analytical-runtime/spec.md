# Spec: Docker analytical runtime

> Status: Phase 1 controlled profile/transport verified; dependent implementation and user-owned runtime validation pending · Slug: analytical-runtime

## Problem

Published datasets can be cataloged, but preview currently returns 503 because
reviewed analytical resources are not injected. The candidate worker transport
and a user-reported container smoke run do not establish complete isolation,
resource enforcement, termination, or API readiness.

## Goal

Provide a reviewed, bounded Docker execution boundary for existing preview and
SQL use cases, with explicit startup ownership and unchanged public contracts.

## Contract authority and evidence

- Public behavior remains defined by [data-api spec](../data-api/spec.md),
  [HTTP contract](../data-api/http-contract.md), [OpenAPI](../data-api/openapi.json)
  and [runtime evidence](../data-api/runtime-evidence.md). This follow-up closes
  execution/composition gaps; it does not redefine pagination or authorization.
- Implemented: candidate image, strict request protocol, one-request worker,
  fail-closed launcher/injection seams, verified modeled cache, snapshot-bound
  previews, retained canonical results and explicitly started result cleanup.
- User-reported, not reproduced here: restricted Docker `SELECT 42 AS answer`
  returned canonical integer-string `"42"`. Authentication, publication and
  catalog work locally. This proves basic execution/transport only.
- Remaining: concrete Docker lifecycle, mount preparation, strict response
  decoding, supervisor ownership/recovery, reviewed measurements and composition.
  Historical Engram finding #328 was revalidated against current seams; no
  historical missing-daemon observation establishes current Docker availability.

## Requirements

### Functional (EARS)

- **FR1:** WHEN an analytical request is admitted THE SYSTEM SHALL authorize its
  complete dataset scope under the current session and role before accessing
  analytical inputs, including cache hits and reference-free queries.
- **FR2:** WHEN preparing execution THE SYSTEM SHALL expose only verified public
  modeled files from its selected published snapshot, read-only and immutable
  for the entire period in which the worker may access them.
- **FR3:** WHEN execution begins THE SYSTEM SHALL run exactly one bounded request
  in a short-lived isolated worker and validate its complete response before
  returning preview rows or retaining a SQL result.
- **FR4:** WHEN cancellation, failure, timeout or shutdown occurs THE SYSTEM SHALL
  terminate the complete worker, confirm its death and reclaim owned container
  resources before releasing execution capacity or input ownership.
- **FR5:** IF worker death cannot be confirmed THEN THE SYSTEM SHALL retain the
  execution slot and input pins, report a safe unavailable/failure outcome and
  transfer recovery ownership to the supervisor without admitting another worker.
- **FR6:** IF creation, daemon access, output decoding, execution or cleanup fails
  THEN THE SYSTEM SHALL preserve the existing safe error vocabulary and expose
  no diagnostic text, SQL, private path, credential or protected metadata.
- **FR7:** WHEN a preview response is decoded THE SYSTEM SHALL preserve the exact
  public column projection, lossless dates/decimals and valid ordered keyset keys
  needed by the existing snapshot/cursor implementation.
- **FR8:** WHEN SQL output is decoded THE SYSTEM SHALL retain one exact canonical
  result document; subsequent pages SHALL reuse it without worker execution,
  query rewriting, normalization or substituted snapshots.
- **FR9:** WHEN the serving supervisor starts THE SYSTEM SHALL reconcile its
  analytical ownership, validate reviewed configuration, and explicitly start
  analytical resources before accepting analytical work.
- **FR10:** WHEN API shutdown or restart occurs THE SYSTEM SHALL manage analytical
  workers and ephemeral state independently of the refresh worker; lost cursors
  and query IDs SHALL remain unavailable without silent reconstruction/reruns.
- **FR11:** WHILE resources are missing, unstarted, incompatible or unreviewed THE
  SYSTEM SHALL fail closed for analytical execution and preserve independent
  catalog, health, authentication and refresh behavior.
- **FR12:** WHEN expiry or orphan cleanup runs THE SYSTEM SHALL reclaim only
  expired or proven-dead analytical ownership, preserving active readers, live
  worker inputs and durable S3/PostgreSQL/refresh artifacts.

### Technical / Non-functional

- **TR1:** Preserve the layered Flask monolith, one codebase, Docker stdin/stdout
  worker and EC2 target. No worker HTTP service, API-process DuckDB fallback or
  user SQL in the refresh worker.
- **TR2:** Enforce non-root execution, no network, read-only root, dropped
  capabilities, no-new-privileges, bounded memory/CPU/processes/private temporary
  storage and minimal environment. Do not mount/pass AWS/database credentials,
  sessions, `.env`, Docker socket, repository, raw artifacts or unrestricted dirs.
- **TR3:** One analytical admission slot covers preparation through confirmed
  termination. Execution/result production is at most ten seconds; preparation,
  overall, Docker control operations and stdout/stderr have explicit hard bounds.
  Uncertain death may retain ownership beyond a deadline; it never implies reuse.
- **TR4:** Preserve 1,000 rows/1,048,576 canonical SQL bytes, existing truncation,
  preview 100/500 paging and fixed 15-minute preview/result lifetimes. Query-ID
  metadata remains bounded and ephemeral outside PostgreSQL.
- **TR5:** Imports, builders and app construction perform no Docker/S3/database
  access, directory preparation, thread startup or refresh work. Process ownership
  and start/close are explicit and safe across startup rollback and repeated close.
- **TR6:** Separate controlled tests from real Docker denial/termination tests and
  representative measurements. Existing engine/container values are candidate
  smoke settings, not reviewed production budgets. T1.7 validation is user-owned;
  do not execute or complete it without explicit direction.

## Inputs & Outputs

Reuse authorized execution/input ports and internal protocol v1 described in
[worker README](../../../infrastructure/analytical-worker/README.md). Inputs are
trusted dataset/digest descriptors and unchanged inspected SQL or preview filters;
paths are fixed `/inputs/<sha256>.parquet`. Outputs are existing `PreviewRows`
and `QueryOutput`, then unchanged public HTTP envelopes. Unknown versions,
operations, properties, duplicate JSON keys, malformed types/cells, inconsistent
counts/limits/keys and oversized output are rejected. No diagnostic passthrough.

## Scope

### In scope

- Docker control, bounded transport/decode, authorized immutable mounts, lifecycle
  ownership/recovery, explicit composition and local startup, tests and readiness
  evidence/checklists.

### Out of scope (non-goals)

- Deployment, provisioning, publication, runtime implementation in this document
  change, API enablement, authorization/schema changes, durable query metadata,
  increased concurrency and independently executed T1.7 validation.

## Assumptions

- The user's successful local authentication/publication observations are context,
  not a request to inspect credentials or publish again.
- Docker is the user-selected implementation approach within accepted isolation
  boundaries; no accepted boundary changes and no new ADR are required here.

## Acceptance Criteria

- [ ] **AC1:** Denied/revoked roles cause zero input reads or launches; cache hits,
  expression-only SQL and continuation requests retain application authorization.
  (FR1, TR1)
- [ ] **AC2:** Only selected public projection files are readable; mutation,
  replacement/symlink races, raw/cache siblings, credentials and network access
  are denied in the real runtime. (FR2, TR2)
- [x] **AC3:** Malformed/duplicate/unknown/oversized responses and invalid canonical
  cells/keys are rejected; real date/Decimal round trips and exact retained bytes
  preserve public encoding. (FR3, FR6–FR8, TR4)
- [ ] **AC4:** Crashes, deadlines, cancellation and daemon/control failures leave no
  surviving worker after confirmed cleanup; uncertain reaping retains capacity,
  files and recoverable ownership. (FR4–FR6, TR3)
- [ ] **AC5:** Startup/factory is inert; explicit start/close/rollback is tested;
  restart reconciles orphan containers before new admission and loses ephemeral
  IDs safely while healthy refresh continues. (FR9–FR12, TR5)
- [ ] **AC6:** Snapshot previews, expiry/revisits, one-execution SQL paging,
  current-role checks, active-reader cleanup and busy responses work through the
  composed API without weakening existing contracts. (FR7–FR12, TR3–TR4)
- [ ] **AC7:** A reviewed evidence record identifies image/profile/platform,
  denial/termination results and measured cold/warm/overlap budgets. User-owned
  T1.7 is closed only with explicit user evidence; API enablement requires a
  separate explicit action after this gate. (FR11, TR6)

## Open Clarifications

No question blocks document preparation. Before readiness, resolve measured
budgets, supported Docker host/daemon/filesystem behavior, API ownership topology,
recovery/storage policy and the concrete evidence-review mechanism in
[plan open decisions](plan.md#open-decisions). These remain unaccepted runtime
choices; neither smoke evidence nor a nonempty evidence string resolves them.
