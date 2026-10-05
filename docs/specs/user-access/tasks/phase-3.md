# Tasks: Reusable role authorization
> Status: complete · Slug: user-access · Plan: ../plan.md · Spec: ../spec.md

## Phase 3: Reusable role authorization (plan phase 3)

- [x] **T3.1** Update pure role policy with trusted operation/grain types and Viewer national-only, Analyst/Admin all-grain, Admin-only refresh initiation/outcome/diagnostic rules; reject unsupported operations/grains and empty analytical scopes — `src/outage_explorer/domain/access.py`. Requires T2.C. (FR7–FR11, FR20)
- [x] **T3.2** Update reusable application authorization entry point to resolve validity/current seeded role before returning a principal/permitted scope — `src/outage_explorer/application/services/access.py`; require complete server-derived dataset sets and fresh checks for every direct/continuation/result invocation. Do not implement analytical services or pass sessions/DB access to workers. Depends on T3.1. (FR5–FR12, FR20, TR4)
- [x] **T3.3** Create table-driven role matrix and downstream spy-use-case tests for all roles/grains/mixed scopes/refresh operations, spoofed roles, missing/invalid/expired/revoked sessions, unavailable stores and repeated page requests — `tests/unit/test_user_access_policy.py`, `tests/unit/test_user_access_authorization.py`; denied operations must produce no data-port/execution call or protected payload. Depends on T3.2. (FR5–FR12, FR20, AC5–AC12, AC20, AC22)
- [x] **T3.C** Checkpoint: run role/authorization tests and architecture/Ruff/mypy checks — `tests/unit/test_user_access_policy.py`, `tests/unit/test_user_access_authorization.py`, `docs/specs/user-access/tasks/phase-3.md`; verify national/detail/Admin matrix and authorize-before-access on direct/later-page harnesses. Record that actual catalog/SQL/refresh routes and SQL-reference/ownership checks remain downstream work. Depends on T3.3. (AC5–AC12, AC20, AC22)


## Checkpoint evidence

- Focused policy/authorization/lifecycle/architecture tests: 213 passed. Broader
  unit/architecture/controlled-provider regression: 577 passed, no skips. Ruff
  lint and format checks pass repository-wide (218 Python files); strict mypy
  passes 72 source files. Diff whitespace checks pass. Python 3.14 was used.
- AC5/AC6: missing/unknown/unassigned/malformed/revoked/expired sessions deny;
  store failures fail closed. Browser role/dataset claims are excluded from the
  authorization inputs and cannot broaden the current seeded role.
- AC7/AC8: the full matrix tests all seven nonempty grain combinations across
  Viewer/Analyst/Admin. Viewer allows only national; Analyst/Admin allow all
  recognized combinations. Empty/unsupported/untyped scopes deny, including
  mixed national/detail references hidden behind a caller's national label.
- AC9–AC11: Admin alone passes trusted refresh initiation/outcome/diagnostic
  checks; Viewer/Analyst and callers without valid sessions deny each operation.
- AC12/AC20: direct and repeated later-page harness calls authorize before any
  data/execution access. Role changes, expiry, revocation and store failure deny
  subsequent pages; spies show zero additional protected access/execution/payload.
  Successful decisions return the seeded principal and exact approved scope;
  workers receive only approved analytical inputs, without session/store access.
- AC22: verification uses fake ports and controlled provider transports, without
  connector completion, analytical data, live accounts or PostgreSQL/cloud writes.
- These checks establish a reusable seam and downstream harness behavior. Actual
  catalog/preview/SQL/result/refresh routes, complete SQL-reference extraction,
  query-result ownership and their own pagination enforcement remain downstream
  implementation work. HTTP composition remains Phase 4.
- An initial repository format check detected concurrent edits in two connector
  tests outside this phase. By the coordinated formatter run both files were
  already formatted and left unchanged; the final repository gate passed.
