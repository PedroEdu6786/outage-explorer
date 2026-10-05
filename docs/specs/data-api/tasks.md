# Tasks: Data browsing, SQL, and background refresh
> Status: draft · Slug: data-api · Plan: ./plan.md · Spec: ./spec.md

## Overview

- 40 tasks across 6 phases; 3 tasks parallelizable [P]. Counts include checkpoints. Hybrid layout: load this manifest and the active phase.
- Existing layer roots and integration seams were checked. Paths marked Create are new files in those roots; add package markers only where required. Preserve concurrent work and work on `main`.

## Phases and dependencies

- [ ] **Phase 1: Contract and runtime feasibility** — [tasks/phase-1.md](tasks/phase-1.md), 8 tasks. T1.1–T1.6 complete; portable contract and compatibility handoff ready. T1.7/runtime checkpoint pending Linux proof and reviewed measurements.
- [ ] **Phase 2: Durable generation and refresh coordination** — [tasks/phase-2.md](tasks/phase-2.md), 6 tasks. Requires the Phase 1 contract; independent of SQL sandbox availability.
- [ ] **Phase 3: Supervised connector integration and recovery** — [tasks/phase-3.md](tasks/phase-3.md), 6 tasks. Requires T2.C; combined production enablement requires the runtime evidence gate.
- [ ] **Phase 4: Authorized catalog and stable previews** — [tasks/phase-4.md](tasks/phase-4.md), 7 tasks. Requires Phase 1 projections and T2.C; controlled tests can proceed before verified sandbox availability, but real execution remains disabled.
- [ ] **Phase 5: One-execution SQL and retained paging** — [tasks/phase-5.md](tasks/phase-5.md), 7 tasks. Requires Phase 1 parser/encoding evidence and Phase 4 cache/execution seams; real execution requires T1.7.
- [ ] **Phase 6: HTTP integration and combined acceptance** — [tasks/phase-6.md](tasks/phase-6.md), 6 tasks. Requires Phases 2–5 and actual runtime evidence for release claims.
- Within a phase follow dependency order. [P] denotes independent siblings after their stated prerequisites, not permission to bypass verification.

## Assumptions and environment gates

- Implement the plan's selected interface choices and synchronize the spec/HTTP contract; maintain proposed status for unreviewed quotas, process topology and sandbox decisions. Accepted architecture changes require a new reviewed ADR.
- The frontend contract artifacts are available in Phase 1; product HTTP endpoints remain Phase 6. Fixtures must identify synthetic inputs and cannot imply running endpoints or published data.
- Linux sandbox denial/limit checks and measured cold/warm preparation, query/storage and overlapping refresh workloads require a suitable verified environment. Darwin checks or a missing Docker daemon cannot close those gates. Keep T1.7 and full T1.C open if evidence is unavailable; independent implementation continues.
- Three retained results per user, ten globally, preview quotas, 183-day refresh maximum and nonaccepted resource limits remain provisional profiles until reviewed; do not invent measurements or enable unsafe defaults.
- Use disposable PostgreSQL and controlled provider/storage artifacts. Live publication, RDS changes, cloud provisioning, deployment and changes to the separate frontend repository require their own authorized scope.
