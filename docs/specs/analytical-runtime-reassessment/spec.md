# Spec: Analytical runtime for a growing query audience
> Status: draft evaluation; no accepted runtime change · Slug: analytical-runtime-reassessment

## Problem
The current analytical runtime rejects a genuine partitioned snapshot before execution and deliberately admits only one analytical request. The application currently has one person managing it; that is an operating fact, not a query-audience or concurrency limit. Query users may grow. The runtime needs a scalable path for concurrent exploration without one query compromising another or making the API unresponsive, while admission stays within an evidence-reviewed operational bound.

## Goal
Select an evidence-based, proportionate execution approach for current operations with one application manager and a potentially growing query audience, while preserving authorized, reproducible analytical results and a future scale path.

## Requirements
### Functional (EARS)
- **FR1:** WHEN multiple authorized users submit analytical requests THE SYSTEM SHALL admit work only within a reviewed aggregate capacity and return an explicit overload outcome for excess demand, without imposing a user-count ceiling from the current operator count.
- **FR2:** WHEN a request executes THE SYSTEM SHALL expose only its authorized immutable public inputs and isolate its execution state and writable resources from other requests.
- **FR3:** WHEN results or previews are continued THE SYSTEM SHALL preserve the selected snapshot, current authorization and one execution's exact retained result without rerunning SQL.
- **FR4:** IF execution fails or its termination is uncertain THEN THE SYSTEM SHALL preserve the affected resource ownership until cleanup is proven and prevent unsafe reuse.
- **FR5:** WHILE analytical work is running THE SYSTEM SHALL retain bounded resources for independent API and refresh work.
- **FR6:** WHEN an execution approach is selected THE ASSESSMENT SHALL compare compatibility, resource enforcement, latency, capacity, operating effort and cost against representative workloads and identify all unverified claims.
- **FR7:** WHEN an alternative keeps Parquet as the durable snapshot but adds a query-serving database projection THE ASSESSMENT SHALL compare its full build, verification, publication, retention, authorization, recovery and query costs against direct Parquet scans before recommending implementation.

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
- Reassess execution isolation, input preparation, bounded concurrency, aggregate resources, ownership/recovery and managed alternatives for a growing query audience managed by one current application operator.
- Distinguish the immediate metadata-size failure from unmeasured compute saturation and longer-term workload growth.
### Out of scope (non-goals)
- Implementation or activation; follows a selected, accepted design and task breakdown.
- Unbounded concurrency is not a design objective. A hard-coded one-user/query ceiling is also not a requirement; admission limits must follow reviewed evidence, with a viable path to future scale. Horizontal API replication remains a separate question.
- Automatic refresh/publication or a changed analytical storage layout; any proposed layout optimization needs its own integrity and publication design before implementation.

## Assumptions
- User confirmed there is currently one person managing the application and that the query audience may grow. This does not specify query-user count or a permanent ceiling; do not infer those from operator count. For evaluation, 2 simultaneous requests is the expected-peak scenario and 4 is the stress scenario. These are evaluation targets, not a demonstrated capacity promise or permanent cap. Unbounded concurrency is not a design objective; a future scale path remains open.
- The owner directed that implementation and isolation tests may continue while latency and resource acceptance limits stay open. This authorizes code and security/lifecycle isolation validation only; performance or capacity measurements remain out of scope until separate numeric acceptance criteria are supplied.
- Preserve synchronous request behavior and explicit busy responses for the baseline; queueing/asynchronous jobs are alternatives requiring deliberate product decisions.
- The currently available snapshot baseline covers six months and contains 549 daily public files totaling 2,199,347 bytes and 27,633 rows. The available snapshots have matching public contents, so they cannot demonstrate changed-content refresh or a second cold transfer. The required future retention/growth horizon remains open.
- The observed failure precedes container creation and does not demonstrate Docker or memory saturation.

## Acceptance Criteria
- [x] **AC1:** The recommendation separates file-count/metadata overhead, execution capacity and operational ownership, with source-backed alternatives and explicit compatibility differences. (verifies FR6)
- [x] **AC1a:** The comparison distinguishes a Parquet-authoritative derived DuckDB serving file, analytical PostgreSQL, and replacing Parquet with a database; it identifies the changed generation/authorization controls and makes no unmeasured latency claim. (verifies FR6–FR7)
- [ ] **AC2:** The design accounts for all concurrent reservations, overload outcomes and API/refresh headroom; experimental worker counts are clearly distinguished from approved budgets. (verifies FR1, FR5)
- [ ] **AC3:** The design defines verifiable request-specific input, state and writable-resource isolation, including mutation and cross-request access failures. (verifies FR2)
- [x] **AC4:** The design preserves snapshot/current-role/retained-result semantics and identifies any alternative that requires a revision. (verifies FR3)
- [ ] **AC5:** The design defines recovery and capacity retention for uncertain workers without releasing their resources or allowing a second owner. (verifies FR4)
- [ ] **AC6:** The plan specifies representative cold/warm, mixed/concurrent, overload, failure, S3 and independently authorized refresh/API overlap measurements; requires numeric workload/resource/operator thresholds before testing; and records how changed profiles affect evidence. (verifies FR1, FR5, FR6)

## Open Clarifications
- Evaluation workload targets are set at 2 simultaneous requests for expected peak and 4 for stress; these are not a permanent cap or demonstrated capacity. One current application manager does not determine query-user count.
- [NEEDS CLARIFICATION: Acceptable preview/SQL time-to-first-page, busy rate and waiting behavior, plus representative expensive-query mix. The owner directed no performance measurements while these remain open.]
- [NEEDS CLARIFICATION: Future retained-data/growth horizon beyond the currently available six-month snapshot baseline.]
- [NEEDS CLARIFICATION: Numeric runtime operator/support-time ceiling, monthly spending ceiling and willingness to change SQL/network/result contracts for a managed service. One current application manager is known; available runtime support time is not.]
- [NEEDS CLARIFICATION: What measured reduction in end-to-end query wait would justify the extra build time, disk and recovery path of a derived DuckDB serving file? No current latency target or measured query duration is accepted.]
- These do not block a proposed comparison. They block claiming a selected production capacity, approved service purchase or completed readiness.
