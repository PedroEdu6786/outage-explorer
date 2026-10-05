# Tasks: EIA data connector
> Status: all six connector phases complete; backend integration deferred · Slug: data-connector · Plan: ./plan.md · Spec: ./spec.md

## Overview

- 54 tasks across 6 phases, including checkpoints; 5 parallelizable [P]. Phases 1–5 contain43 tasks; phase6 contains11 tasks including page-fetch and verification-performance extensions. All54 connector tasks are complete. Hybrid layout keeps implementation scoped to one phase.
- [Phase 1: Pure merge, provenance and accounting](tasks/phase-1.md) — complete; 7 tasks. Recorded checkpoint: 366 tests plus Ruff, mypy and package builds passed.
- [Phase 2: Parquet schemas, replay and candidate verification](tasks/phase-2.md) — complete; 7 tasks. Recorded checkpoint: 430 tests plus dependency, Ruff, mypy and package checks passed; local candidate guarantees only.
- [Phase 3: Bounded source adapter](tasks/phase-3.md) — complete; 6 tasks. Recorded checkpoint: 584 tests, including 143 source and 4 transport tests, plus dependency, Ruff, mypy and build checks passed. Live paging/order and production limits remain unproven.
- [Phase 4: Runnable local connector](tasks/phase-4.md) — complete; 13 tasks. Recorded checkpoint: 687 tests (90 new connector tests), dependency, Ruff, mypy and package checks passed. Local CLI/configuration/reports, exact-prior reruns and failure checks; no live or publication guarantees.
- [Phase 5: Durable connector artifacts in S3](tasks/phase-5.md) — complete (controlled SDK checkpoint); 10 tasks; depends on phase 4. Persist/recover the entire immutable candidate graph by exact reference, with controlled SDK fault checks.
- [Phase 6: Controlled live connector validation](tasks/phase-6.md) — complete; full initial live candidate and exact configured-S3 recovery verified;11 tasks; depends on phase 5 and applicable live/cloud authorization. Record actual paging/order, sequential/concurrent interval/resource, rerun and S3 recovery evidence; implement bounded endpoint processing and S3 upload/readback concurrency after baseline measurements.
- The revised plan now uses these same six phase numbers. Completed phase files remain unchanged historical evidence; their old plan-phase labels reflect the earlier five-phase plan, not the current sequence.
- Execute only the current phase. Phase-2 and phase-4 [P] markers now remain historical. Later phases wait for earlier checkpoints; independent controlled work need not wait for EC2 deployment or backend integrations.
- Paths marked **new** are intended additions under existing packages; previously introduced paths must exist at their dependent task. This breakdown writes no implementation and authorizes no live requests, cloud writes, deployment, commits or automatic next phase.

## Requirement coverage and deferred acceptance

- **FR4–FR8:** completed phases 1–3 plus T4.5/T4.9/T4.10; checkpoint T4.C verifies local AC3–AC7. T6.1/T6.2/T6.C cover live paging, ordering, applicability and measured bounds. FR5/AC4 active-generation preservation remains a backend obligation.
- **FR9–FR13:** completed merge/Parquet policies plus T4.5/T4.11; T4.C verifies AC8–AC12 candidate behavior, including no-prior/partial/all-excluded decisions and exact grain-independent values. T6.4/T6.C add supported live-candidate evidence. AC10 initial publication and AC11 publication prevention remain backend obligations.
- **FR14–FR16:** source/model summaries plus T4.4/T4.10/T4.11; T4.C and T6.C verify AC13–AC15 within demonstrated local/live scope. Facility mismatches stay visible/nonblocking by themselves; known failed pages still fail.
- **FR6 and FR17–FR20 artifact portions:** T5.2–T5.8 and T5.C verify AC5 graph replay and AC17–AC18 integrity/recovery with controlled storage; T6.5/T6.C verify separately authorized AWS behavior. Exact persisted candidates do not prove activation, durable refresh outcomes or reader pinning.
- **TR1–TR4:** completed contracts/Parquet plus T4.1–T4.8, T4.10/T4.11 and phase-5 storage tasks; T4.C/T5.C check boundaries, exact representation and sanitized replay. S3 authoritative storage remains required; DuckDB execution is separate and unimplemented.
- **TR5–TR8:** T4.2/T4.5/T4.9–T4.11 verify bounded candidate behavior; T6.1–T6.3 and T6.C establish only measured live applicability/limits. Initial dates remain April 2–October 1, 2026 inclusive; explicit candidate intervals may be smaller. Enforceable deployed worker limits remain backend enablement work.
- **TR9:** T4.5/T4.11/T4.C cover candidate eligibility and retained provenance; T6.2/T6.4/T6.C cover the accepted initial-interval candidate when supported. Authorized initial publication remains deferred.
- **TR12/AC20:** T6.2b/T6.C implement and verify parallel conditional S3 uploads/readback with shared bounds, final-root ordering, exact graph equivalence and failure cleanup; T6.5 records separately authorized AWS comparisons.
- **TR11/AC19:** T6.2a/T6.C implement and verify bounded endpoint concurrency, deterministic selection/retention, aggregate budgets and failure cleanup; sequential/live comparisons establish supported settings.
- **TR10:** T4.3/T4.11 preserve prior candidates; T5.4/T5.8/T5.C and T6.5/T6.C verify inherited durable dependencies without source access. No automatic authoritative-data deletion or recovery-policy design is added.
- **Explicitly deferred FR1–FR3; remaining FR17–FR20, TR1/TR5/TR9–TR10 product portions; AC1–AC2 and AC16; publication/outcome portions of AC4/AC10/AC11/AC17–AC18:** later backend integration must implement Admin authorization, durable run/outcome records, admission/leases/fencing, independent supervision, atomic activation, reader pinning, uncertain-commit reconciliation and operational restart recovery. Ownership remains the deferred integration sections of [the connector plan](plan.md) and [backend plan](../outage-explorer-backend/plan.md); generate its task breakdown when that scope resumes. No current connector task or checkpoint closes these requirements.
- Every FR/TR/AC is accounted for above as executable connector work or explicit deferral. Full-spec task/acceptance coverage is deliberately incomplete under the approved connector-only sequencing; keep spec acceptance checkboxes open unless every part has actual evidence.

## Open decisions and affected gates

- No open decision blocks the phase-4 breakdown. Reuse Python policies, PyArrow 25.0.1 and HTTPX 0.28.1; do not rewrite processing into DuckDB or introduce a database for local candidate execution.
- **Q1:** explicit test budgets support local implementation; T6.2–T6.3 must measure supported interval/request/arithmetic/memory/disk/output ranges. Never misclassify resource exhaustion as row exclusion. Unproven hard worker limits remain a backend enablement gate.
- **Q3–Q4:** T6.1 establishes observed route paging/termination/order and contract applicability beyond September. No source-recency or completeness guarantee follows from response order, observed rosters or advertised totals; facility-total investigation is not a prerequisite.
- **S3 SDK:** select/pin in T5.1 and test actual immutable-write/readback behavior before claiming AWS evidence. Existing bucket setup alone does not implement the adapter.
- **Accepted policies:** [ADR-0037](../../adr/0037-connector-initial-load-and-retention.md) preserves absent-key and partial-route retention and requires usable output in all three grains for initial publication. Candidate generation grants no publication rights.
- **Local development:** [ADR-0038](../../adr/0038-ec2-deployment-local-development.md) makes EC2 a deployment target, not a prerequisite. User-reported RDS/Cognito setup does not implement backend adapters; those integrations and PostgreSQL tooling remain deferred backend work.


- **TR13 / AC21:** T6.7 completed bounded intra-route page windows, canonical
  received-count repair, exact supplemental evidence/recovery and explicit fetch/
  S3 Make/CLI overrides. The subsequent full initial live candidate and exact configured-S3 recovery close T6.4/T6.C; backend activation remains deferred.
