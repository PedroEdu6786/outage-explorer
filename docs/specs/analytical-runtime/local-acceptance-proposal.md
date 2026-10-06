# Proposed local preview/SQL acceptance scope

Status: local scope approved in [ADR-0055](../../adr/0055-scoped-local-analytical-readiness.md);
matching analytical/parser report and initial-limit review approved by the user
on October 6, 2026. The review is recorded in
[local report review evidence](evidence/2026-10-06-local-report-review.json).
Activation and remaining local auth/resource checks remain open.

## One scope decision

Allow a separate local preview/SQL acceptance checkpoint before complete
capacity benchmarking. Defer complete sampled/high-water and query-spill workload
measurements, product S3 cold-cache/transfer performance and API/refresh capacity
overlap to the broader T4.3/T4.C and original data-api T1.7/T1.C checkpoints.
Keep those original checkpoints open with their actual missing evidence.

Recommendation: accept this limited local path. Existing passing native denial,
quota, termination, parser owner-loss, preview and retained-result evidence can
support initial containment settings without claiming measured production budgets.
Further benchmarking or tuning is needed only for a demonstrated local safety
or correctness blocker. Production/release and simultaneous refresh/query capacity
acceptance retain their broader requirements. Local acceptance exercises preview
and SQL with refresh idle; it grants no refresh or publication direction.

This narrows the pre-local-start measurement dependency in analytical-runtime
AC7/TR6 and T5.1, data-api TR5/Q2, and the pre-release combined-capacity requirement
of ADR-0013 **for local acceptance only**. ADR-0055 records the accepted refinement;
the explicit local checkpoint is in [tasks.md](tasks.md). Historical ADRs and
the original full-evidence checkpoints remain intact.

## Safeguards retained before any startup

1. The user reviewed the actual matching analytical reports, missing coverage
   and complete configuration, and accepted initial containment limits. The exact
   profile/report identities and approval are recorded in the review evidence.
   The 10-second execution, 1,000-row/1-MiB output and fixed pagination lifetimes
   remain intact. Parser numeric-cap acceptance alone is insufficient.
2. The user separately approved the full parser configuration and matching
   reports in [parser-review.md](parser-review.md). The source candidate remains
   inert; matching reviewed local runtime configuration is stored outside the
   repository, with reviewer/date/report identities recorded.
3. Use the native Linux controller/daemon boundary, non-root UID/GID, no worker
   network or credentials, exact immutable authorized inputs, hard memory/PID/CPU
   and dedicated ext4 byte/inode/noexec enforcement. Retain confirmed termination,
   uncertain-ownership admission retention, recovery and rollback. Preserve current
   role checks before parsing/inputs and on every continuation.
4. Confirm the actual serving host and exact executable/profile/root/daemon/mount
   identities. The recorded Linux validation host can reuse its matching evidence;
   the Mac cannot run this Linux parser/disk backend. New roots/platform/image
   identities require explicit evidence mapping and affected checks. Builders and
   CLI help remain inert. Do not transfer credentials to create benchmark workloads.
5. Confirm trusted-host access to the existing PostgreSQL and S3 publication, seeded
   role bindings and Cognito callback/client configuration without secret output.
   A local connector candidate or S3 receipt does not substitute for published
   data. Verify product S3 integrity/cache behavior during authorized endpoint
   acceptance; only its performance measurements would be deferred.
6. Retain the outstanding real Cognito/application-role and pooled-IAM requirements
   below. This scope decision does not waive user-access T5.14/T5.C.
7. Obtain **separate explicit activation direction** after matching readiness review.
   Then run Phase 5 HTTP acceptance: all-grain previews, current-role denial,
   reference-free and dataset SQL, one-execution result paging, expiry/ownership,
   busy/failure isolation and restart/rollback. Test clients and native direct
   workloads are supporting evidence, not performed Phase 5 acceptance.

## Exact authentication requirements

The October 5 user acceptance establishes integrated Viewer login, session and
logout behavior; it does not supply all-persona/browser evidence. Preserve it.
Remaining user-access T5.14/T5.C requires real Analyst/Admin login and local role
resolution, generic invalid-credential presentation, fixed one-hour expiry,
persistent-browser reopening without renewal, expiry/old-cookie denial and
independent sessions surviving another session's logout. Existing controlled
tests cover these policies; no further implementation is implied by missing live
evidence. Verify current seeded issuer/subject bindings, confirmed provider users,
exact callback/origins/scopes and confidential/public-client configuration.

Pooled IAM requires current trusted runtime-user TLS connectivity through the
application pool, fresh bounded signing for each new physical connection/retry,
no signing for existing checkout, no password fallback and no application/provider
session renewal. The controlled suite covers reconnect at virtual 901 seconds,
retry, concurrency and failure. Historical direct-token and application-pool
success alone do not prove the current configured fresh-signing path. A current
read-only pool/replacement check can close that connectivity gap without starting
the API or writing application state; do not claim a real 15-minute wait or live
browser session continuity from it. No mandatory real-time wait is specified in
T5.4; session continuity still belongs to real browser acceptance.

## Evidence to reuse

- [Native directory-mount isolation](evidence/2026-10-05-colima-isolation-directory-mount.json):
  19 probes for the recorded analytical image/profile, including hard disk quota,
  denial, resource exhaustion, termination and recovery.
- [Preview/SQL observations](evidence/2026-10-06-preview-sql-local-resource-observations.json):
  27 previews, six SQL executions, three retained-page reads, 301 samples covering
  all 33 containers and zero failures. Sampled maxima are not complete high-water.
- [Independent cleanup](evidence/2026-10-06-preview-resource-cleanup.json):
  zero active measurement-owned resources.
- [Parser packet](parser-review.md): 18 native lifecycle/resource/owner-loss checks,
  exact candidate ownership-path start/inspect/close and accepted numeric caps.

Analytical image: `sha256:1ee90c05fa1c8578b3240f4eb39382103fe948f190d9ec0b8e3593440cd9b176`.
Analytical profile: `a227d729593bcff61f301df141e2479301c7cf9fbf91ea0ebe8891c33611f57f`.
Parser profile: `833fd37713f21542d3ffca7bb0d34d237441c7a145c4b35463deef1cc6649669`.

Approval of this scope alone approves no configuration budget, parser report,
serving-host change, startup, endpoint activation, refresh, publication or deployment.
