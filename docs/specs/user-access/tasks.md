# Tasks: Seeded users, login, and role access
> Status: draft · Slug: user-access · Plan: ./plan.md · Spec: ./spec.md

## Overview

- 35 tasks across 5 phases; 6 tasks parallelizable [P]. Counts include phase checkpoints. Hybrid layout: load this manifest and only the current phase during implementation.
- Existing paths were checked against the repository; paths marked **Create** are proposed additions within existing layer/package roots, including new `infrastructure/postgresql/`, `infrastructure/cognito/`, and `tests/acceptance/` packages. Add package markers where required by existing import/build conventions, without re-exporting concrete adapters into inner layers.

## Phases and dependencies

- [x] **Phase 1: Storage and controlled account linkage** — [tasks/phase-1.md](tasks/phase-1.md), 9 tasks; starts independently of the connector.
- [x] **Phase 2: Provider verification and fixed sessions** — [tasks/phase-2.md](tasks/phase-2.md), 8 tasks; requires T1.C.
- [x] **Phase 3: Reusable role authorization** — [tasks/phase-3.md](tasks/phase-3.md), 4 tasks; requires T2.C.
- [x] **Phase 4: HTTP composition and browser transport** — [tasks/phase-4.md](tasks/phase-4.md), 8 tasks; requires T3.C.
- [ ] **Phase 5: Independent acceptance and provider readiness** — [tasks/phase-5.md](tasks/phase-5.md), 6 tasks; requires T4.C.
- Within each phase, tasks are sequential unless an explicit dependency permits otherwise; [P] identifies independent sibling work after its stated prerequisite, not permission to bypass checkpoints.

## Assumptions and remaining inputs

- Preserve the draft plan's cookie/session/tooling recommendations; T1.1 records them as proposed decisions, without changing accepted ADRs or claiming user acceptance. Concrete pins, database version compatibility, provider identifiers, seed subjects/emails and callback/UI origins are implementation inputs, not new product questions.
- T1.C uses disposable local PostgreSQL tests and provider fakes; it does not require production/RDS seeding or Cognito provisioning. Missing provider configuration blocks only T5.5 and the live-readiness portion of T5.C.
- Preparing migration/seed commands and a runbook does not authorize running them against RDS or creating/updating Cognito accounts. Live resource writes require explicit existing/session authorization; provider smoke uses authorized provisioned personas and reports incomplete checks honestly.
- No connector, analytical endpoints, refresh execution, separate UI, deployment or restart-recovery machinery is implemented. Authorization harnesses validate reusable seams; later feature implementations must test their own data references, ownership and page enforcement.
