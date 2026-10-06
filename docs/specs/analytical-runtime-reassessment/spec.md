# Spec: Analytical runtime for a small concurrent team
> Status: draft evaluation; no accepted runtime change · Slug: analytical-runtime-reassessment

## Problem
The current analytical runtime rejects a genuine partitioned snapshot before execution and deliberately admits only one analytical request. A small team needs concurrent exploration without one query compromising another or making the API unresponsive; the runtime choice and operational effort need reassessment before further tuning.

## Goal
Select an evidence-based, proportionate execution approach for a small concurrent team while preserving authorized, reproducible analytical results.

## Requirements
### Functional (EARS)
- **FR1:** WHEN several team members submit analytical requests THE SYSTEM SHALL admit work only within a reviewed aggregate capacity and return an explicit overload outcome for excess demand.
- **FR2:** WHEN a request executes THE SYSTEM SHALL expose only its authorized immutable public inputs and isolate its execution state and writable resources from other requests.
- **FR3:** WHEN results or previews are continued THE SYSTEM SHALL preserve the selected snapshot, current authorization and one execution's exact retained result without rerunning SQL.
- **FR4:** IF execution fails or its termination is uncertain THEN THE SYSTEM SHALL preserve the affected resource ownership until cleanup is proven and prevent unsafe reuse.
- **FR5:** WHILE analytical work is running THE SYSTEM SHALL retain bounded resources for independent API and refresh work.
- **FR6:** WHEN an execution approach is selected THE ASSESSMENT SHALL compare compatibility, resource enforcement, latency, capacity, operating effort and cost against representative workloads and identify all unverified claims.

### Technical / Non-functional
- **TR1:** Existing broad read-only analytical SQL, role restrictions, public schemas, immutable snapshot identity and pagination behavior remain the comparison baseline; alternatives must list every required contract change.
- **TR2:** Preserve current ten-second execution ceiling, separate preparation/overall bounds, 1,000-row/1-MiB result caps and fixed continuation expiry unless separately accepted changes are documented.
- **TR3:** The default comparison retains one product and one API owner; assess concurrent execution without assuming extra API replicas, a broker or durable query-ID metadata.
- **TR4:** Preserve completed implementation phases and historical evidence. Changed boundaries/profiles require explicit decision records and affected validation before enablement.
- **TR5:** Evaluate user SQL outside the credential-bearing API process; engine settings and syntax validation alone do not establish isolation.
- **TR6:** Evaluation planning authorizes no source refresh, publication, deployment, credential transfer, paid-service trial or API enablement. Actual measurements require suitable existing inputs and separately authorized workloads.

## Inputs & Outputs
- Inputs: existing public snapshot descriptors and representative SQL/preview requests; measured current admission failure; current contracts and runtime evidence; primary-source service documentation.
- Outputs: proposed approach, alternatives and compatibility differences, design-level phases, decision/dissent record, and measurable validation gates. This document introduces no HTTP fields or result schema.

## Scope
### In scope
- Reassess execution isolation, input preparation, bounded concurrency, aggregate resources, ownership/recovery and managed alternatives for a small team.
- Distinguish the immediate metadata-size failure from unmeasured compute saturation and longer-term workload growth.
### Out of scope (non-goals)
- Implementation or activation; follows a selected, accepted design and task breakdown.
- Unbounded concurrency or horizontal API replication; revisit if measured small-team capacity is insufficient.
- Automatic refresh/publication or a changed analytical storage layout; any proposed layout optimization needs its own integrity and publication design before implementation.

## Assumptions
- User confirmed evaluation of a small concurrent team. Compare 2 and 4 simultaneous requests as provisional scenarios, not accepted capacity promises.
- Preserve synchronous request behavior and explicit busy responses for the baseline; queueing/asynchronous jobs are alternatives requiring deliberate product decisions.
- Current candidate snapshots contain 549 daily public files totaling 2,199,347 bytes and 27,633 rows each. Their public contents match; they cannot demonstrate changed-content refresh or a second cold transfer.
- The observed failure precedes container creation and does not demonstrate Docker or memory saturation.

## Acceptance Criteria
- [ ] **AC1:** The recommendation separates file-count/metadata overhead, execution capacity and operational ownership, with source-backed alternatives and explicit compatibility differences. (verifies FR6)
- [ ] **AC2:** The design accounts for all concurrent reservations, overload outcomes and API/refresh headroom; experimental worker counts are clearly distinguished from approved budgets. (verifies FR1, FR5)
- [ ] **AC3:** The design defines verifiable request-specific input, state and writable-resource isolation, including mutation and cross-request access failures. (verifies FR2)
- [ ] **AC4:** The design preserves snapshot/current-role/retained-result semantics and identifies any alternative that requires a revision. (verifies FR3)
- [ ] **AC5:** The design defines recovery and capacity retention for uncertain workers without releasing their resources or allowing a second owner. (verifies FR4)
- [ ] **AC6:** The plan specifies representative cold/warm, mixed/concurrent, overload, failure, S3 and independently authorized refresh/API overlap measurements; requires numeric workload/resource/operator thresholds before testing; and records how changed profiles affect evidence. (verifies FR1, FR5, FR6)

## Open Clarifications
- [NEEDS CLARIFICATION: Peak simultaneous team demand and acceptable preview/SQL time-to-first-page, busy rate and waiting behavior.]
- [NEEDS CLARIFICATION: Required retained-data horizon and representative expensive-query mix beyond the current six-month snapshots.]
- [NEEDS CLARIFICATION: Operator availability, monthly spending ceiling and willingness to change SQL/network/result contracts for a managed service.]
- These do not block a proposed comparison. They block claiming a selected production capacity, approved service purchase or completed readiness.
