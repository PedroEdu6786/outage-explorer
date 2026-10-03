# Tasks: EIA data connector
> Status: phases 1–2 complete; later phases draft · Slug: data-connector · Plan: ./plan.md · Spec: ./spec.md

## Overview

- 40 tasks across 6 executable phases; 2 tasks parallelizable [P]. This manifest links granular phase files to keep implementation focused.
- [Phase 1: Pure merge, provenance and accounting](tasks/phase-1.md) — complete, including confirmed product policies; plan phase 1, independent foundation. `make check`: 366 tests passed, including 52 connector tests; Ruff, mypy and package builds passed.
- [Phase 2: Parquet schemas, replay and candidate verification](tasks/phase-2.md) — complete; remainder of plan phase 1. `make check`: 430 tests passed, including 64 new phase-2 tests; Ruff, mypy, dependency checks and package builds passed. Live/cloud/publication acceptance remains pending.
- [Phase 3: Bounded source adapter](tasks/phase-3.md) — pending; plan phase 2; depends on phase 2 evidence contracts.
- [Phase 4: Durable refresh and generation commit](tasks/phase-4.md) — pending; plan phase 3; depends on phases 1–2; fixture sources allow progress independently of live enablement.
- [Phase 5: Authorized orchestration and initial load](tasks/phase-5.md) — pending; plan phase 4; depends on phases 2–4 and verified application identity/permission integration.
- [Phase 6: Live enablement evidence](tasks/phase-6.md) — pending; plan phase 5; depends on phases 1–5 and the corresponding open decisions below.
- Splitting plan phase 1 changes execution granularity only. Phase 1 introduces no dependency, physical schema, runtime, publication or source-access decision. Pure checks establish only the unit-level portions of acceptance criteria; storage, authorization, live retrieval and publication remain later checkpoints.
- New file paths below follow the existing layer-first packages; they are intended additions, not claims that adapters already exist. Existing `domain/observations.py`, offline verifiers and their report contracts remain the behavior baseline.

## Open decisions and affected gates

- **Confirmed product policies:** the user confirmed the devlog decisions during implementation; [ADR-0037](../../adr/0037-connector-initial-load-and-retention.md) records initial live loading for April 2–October 1, 2026, absent-key retention and partial-route retention while other valid updates proceed. Runtime publication still requires all integrity and authorization checks.
- **Q1:** caller-supplied test caps permit phase 1; measure production interval, arithmetic, request, memory, disk and output budgets before phase 6 enablement. Never turn a resource failure into an excluded row.
- **Q2 resolved:** retain absent prior keys and their origins; report absence separately from invalid replacement. Initial dates are explicit and inclusive; no automatic rolling anchor is selected.
- **Q3–Q4:** fixture retrieval is independently implementable; establish live pagination, termination, ordering/ties and broader contract applicability before claiming live guarantees. Facility advertised-total investigation remains deferred and nonblocking by itself.
- **Q5 resolved:** wholly excluded refresh routes retain previous data while valid updates from other routes proceed. Every route excluded retains the active generation unchanged. Initial live loading must produce usable output for all three routes before first publication.
- **Adapter and schema choices:** review/pin Parquet, HTTP, S3 and PostgreSQL dependencies/tooling before their affected adapter tasks. Typed decimals plus source strings and explicit representation failure are accepted; concrete physical widths and exact round trips still require verification. Physical representability never narrows the accepted source validation grammar.
- **Runtime integrations:** verified session-to-application-principal mapping and application permissions gate exposed refresh; ECS supervision and enforceable worker resource bounds gate runtime enablement. Fakes and local integration evidence do not close AWS or runtime gaps.
- **Authorization scope:** implement and test local artifacts under the current user request. Live credentialed evidence collection, provisioning, deployment and external data publication need their own applicable authorization; no commit or network action is part of this task breakdown.
