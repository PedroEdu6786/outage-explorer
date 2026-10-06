# ADR-0055: Separate local analytical readiness from capacity acceptance

Status: **Accepted by user direction**

Date: 2026-10-06

Refines ADR-0007/0008/0013 and analytical-runtime AC7/TR6 for local acceptance
only. Preserves ADR-0053 single-owner topology and ADR-0054 parser isolation.

## Context

Native isolation/quota/termination probes, parser owner-loss/resource checks,
27 previews, six SQL executions and three retained-result page reads passed.
301 resource samples covered all 33 analytical containers without failure.
Complete high-water/spill, product S3 performance and API/refresh overlap evidence
remain absent. The user prioritized local preview/SQL enablement and explicitly
approved the [narrow proposal](../specs/analytical-runtime/local-acceptance-proposal.md).

## Decision

- Introduce a separately reviewed **local preview/SQL readiness checkpoint**.
  It may precede complete high-water/spill workload, product S3 performance and
  API/refresh capacity-overlap measurements. Reuse existing matching evidence;
  further measurement/tuning is required for demonstrated local safety or
  correctness blockers, rather than solely to improve existing numbers.
- Keep refresh idle during this local preview/SQL acceptance. Preserve independent
  refresh supervision. Simultaneous refresh/query capacity and production/release
  readiness retain their broader evidence requirements.
- Preserve original T4.3/T4.C and data-api T1.7/T1.C as open complete-evidence
  checkpoints; deferred checks are not passed or deleted. Local readiness can
  satisfy the Phase 5 startup dependency only after its own review passes.
- Retain application authorization, exact authorized read-only inputs, worker
  credential/network denial, hard resource bounds, bounded parser inspection,
  confirmed termination, uncertain-ownership retention and restart/rollback.
  User review must accept actual matching reports and initial containment limits;
  do not call those settings measured production budgets.
- Retain real auth acceptance, current pooled-IAM access, actual Linux serving-host
  profile/executable/path/quota verification and correctness of published S3 input
  retrieval. Deferring S3 performance does not waive integrity or authorization.
- Record `acceptance_scope: "local-preview-sql"` in a future approved analytical
  evidence record. Generic runtime readiness must reject that record unless the
  caller explicitly requests local acceptance. Exact profile/report identities,
  user reviewer/date and separate parser review remain mandatory.

This scope approval grants no budget/report approval, API startup, endpoint
activation, refresh, publication, deployment or credential transfer. Activation
still requires separate direction after applicable readiness review.

## Alternatives and consequences

Keeping complete benchmarking before local startup preserves the former sequencing
but delays endpoint acceptance despite passing isolation and functional evidence.
Waiving containment or auth is unacceptable. The selected scope preserves those
safeguards and explicitly limits what local evidence can establish.

No higher concurrency, SQL surface restriction, profile limit increase, new cloud
resource or production capacity claim is authorized. Historical failed attempts
and missing coverage remain visible alongside passing evidence.
