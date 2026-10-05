# Tasks: Seeded users, login, and role access
> Status: phases 1–4 complete original checkpoints; phase 5 controlled tasks complete, live checkpoint pending · Slug: user-access · Plan: ./plan.md · Spec: ./spec.md

## Overview

- 44 tasks across 5 phases; 8 tasks parallelizable [P]. Counts include phase checkpoints. Hybrid layout: load this manifest and only the current phase during implementation.
- Existing paths were checked against the repository; paths marked **Create** are proposed additions within existing layer/package roots, including phase-5 credential/HTTP helper modules and acceptance tests. PostgreSQL/Cognito packages and auth routes already exist from phases 1–4. Add package markers where required by existing import/build conventions, without re-exporting concrete adapters into inner layers.

## Phases and dependencies

- [x] **Phase 1: Storage and controlled account linkage** — [tasks/phase-1.md](tasks/phase-1.md), 9 tasks; starts independently of the connector.
- [x] **Phase 2: Provider verification and fixed sessions** — [tasks/phase-2.md](tasks/phase-2.md), 8 tasks; requires T1.C.
- [x] **Phase 3: Reusable role authorization** — [tasks/phase-3.md](tasks/phase-3.md), 4 tasks; requires T2.C.
- [x] **Phase 4: HTTP composition and browser transport** — [tasks/phase-4.md](tasks/phase-4.md), 8 tasks; requires T3.C.
- [ ] **Phase 5: Live connection support, reusable HTTP protection and acceptance** — [tasks/phase-5.md](tasks/phase-5.md), 15 tasks; requires T4.C.
- Within each phase, tasks are sequential unless an explicit dependency permits otherwise; [P] identifies independent sibling work after its stated prerequisite, not permission to bypass checkpoints.

## Assumptions and remaining inputs

- Preserve completed phases 1–4 and their original controlled-test checkpoints. Phase 5 now implements per-new-physical-connection IAM signing, confidential Cognito client support and reusable typed authentication/CSRF/query-and-JSON validation decorators before the original acceptance/browser/CI/runbook/live-verification work. Old unchecked phase-5 tasks were expanded and renumbered; original scope remains covered by T5.10–T5.14.
- ADR-0046/0047 remain proposed integration/tooling records; no accepted boundary changes. Database credential refresh never renews provider tokens or changes the fixed application-session lease. HTTP helpers cannot replace fresh application-owned session/role checks on protected use cases.
- Dated setup evidence in [plan.md](plan.md): prior checks verified Aurora PostgreSQL 17.9, `outage-explorer-db`, runtime role `outage_app`, verify-full IAM connectivity/schema reads and three trusted seeded role bindings. Cognito control reads verified email login, disabled self-registration and JWKS; the existing client has a secret and captured accounts required first-login password changes. These findings must be revalidated for phase-5 live acceptance; this task update reruns no cloud checks.
- Local AWS profile `outage-explorer` resolved to root before the guided setup; the user chose to keep the profile name. Revalidate its current underlying identity before live checks rather than assuming the credentials remain root. Identity replacement or EC2 setup is not a local phase-5 implementation blocker. Production least-privilege configuration remains a deployment input.
- Exact public callback/backend/frontend origins and allowed return paths, confidential client secret/provider domain/scopes, explicit database IAM configuration and first-login password completion remain live implementation inputs. Environment variables exported in another terminal are not automatically visible. Controlled PostgreSQL/provider/browser work proceeds independently; missing live inputs block T5.14 and overall T5.C completion until actual required live checks pass.
- Preparing migration/seed commands and the runbook does not authorize executing new RDS writes or creating/updating Cognito resources. Live changes require explicit existing/session authorization; no publishing/deployment/commit is implied.
- This auth effort excludes implementing product analytical/refresh endpoints, separate UI, deployment or restart-recovery machinery. Authorization harnesses validate reusable seams; downstream feature implementations must test their own references, ownership and page enforcement. Connector completion is not an auth acceptance prerequisite.


## Phase 5 current result

T5.1–T5.13 are complete with 1381 tests and 17 subtests passing (zero skips),
Ruff/mypy/dependency/whitespace checks and sdist/wheel build on Python 3.14.6.
T5.14, T5.C and the Phase 5 checkbox remain pending because real managed-login
and browser verification was explicitly deferred. See [verification.md](verification.md)
for AC1–AC22 controlled/live reconciliation and the exact commands.
