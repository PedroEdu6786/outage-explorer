# Tasks: HTTP composition and browser transport
> Status: complete · Slug: user-access · Plan: ../plan.md · Spec: ../spec.md

## Phase 4: HTTP composition and browser transport (plan phase 4)

- [x] **T4.1** [P] Create auth HTTP schemas and sanitized error translation for current identity/role/expiry/CSRF output, generic login failure and 400/401/403/503 categories; exclude tokens and protected payloads and set no-store — `src/outage_explorer/entrypoints/http/schemas.py`, `src/outage_explorer/entrypoints/http/errors.py`. Requires T3.C; independent of T4.2. (FR4, FR19, FR20)
- [x] **T4.2** [P] Create browser cookie/origin transport helpers with host-only persistent absolute expiry, HttpOnly/Lax, production Secure/`__Host-` and explicit local-HTTP mode, attempt binding cookies, CSRF header extraction, exact mutation-origin checks and configured credentialed-origin handling — `src/outage_explorer/entrypoints/http/auth_transport.py`; cryptographic checks stay in the injected application/security seam. Requires T3.C; independent of T4.1. (FR12–FR18, FR20, TR1–TR3)
- [x] **T4.3** Create thin login/callback/session/logout blueprint delegating to injected services, using allowlisted redirects, session-bound CSRF on logout, idempotent invalid-session cookie clearing and committed invalidation before 204 — `src/outage_explorer/entrypoints/http/routes/access.py`; no direct provider/database/domain policy calls. Depends on T4.1, T4.2. (FR2, FR4, FR5, FR12–FR20)
- [x] **T4.4** Update typed configuration, composition/lifecycle and HTTP service registration for configured Cognito/PostgreSQL adapters, fixed session lifetime, callback/origin/cookie/attempt settings and protected auth routes — `src/outage_explorer/settings.py`, `src/outage_explorer/bootstrap.py`, `src/outage_explorer/entrypoints/http/app.py`, `.env.example`; preserve health-only construction without credentials, imports/factories without connections/network/migrations/refresh, process-owned cleanup and deterministic invalid-config failures. Depends on T4.3. (FR2, FR12–FR18, TR1–TR4)
- [x] **T4.5** Create HTTP behavioral tests for routes, identity, flags/absolute expiry, failed callbacks, CSRF/origins/redirects, generic no-store errors, expired/replayed sessions and independent logout — `tests/integration/test_user_access_http.py`; extend inert-startup/health coverage in `tests/integration/test_startup.py`, `tests/integration/test_health_http.py`. Depends on T4.4. (FR2, FR4, FR12–FR20, AC2, AC4, AC12–AC20, AC22)
- [x] **T4.6** Create browser-to-Flask integration contract and update separate-client handoff for proposed routes, expiry/re-login, credentialed requests, CSRF and same-origin development proxy versus explicit permitted origin configuration — `docs/specs/user-access/http-contract.md`, `docs/context/ui-client/04-backend-integration.md`; label draft choices and exclude separate UI implementation or a token bridge. Depends on T4.5. (FR2, FR4, FR13–FR20, TR4)
- [x] **T4.7** Extend architecture fixtures for auth-route inward dependencies, security/provider/database imports restricted to infrastructure and inert HTTP registration — `tests/architecture/test_import_boundaries.py`; preserve exact startup exception and all negative fixtures, narrow any required checker change in `tests/architecture/import_rules.py`. Depends on T4.6. (FR12, TR1, TR2, TR4, AC22)
- [x] **T4.C** Checkpoint: run HTTP/startup/health and architecture suites plus Ruff/mypy — `tests/integration/test_user_access_http.py`, `tests/integration/test_startup.py`, `tests/integration/test_health_http.py`, `tests/architecture/test_import_boundaries.py`, `docs/specs/user-access/tasks/phase-4.md`; verify transport behavior and no protected leakage or startup I/O; real browser reopening is checked in Phase 5. Depends on T4.7. (AC2, AC4, AC12–AC14, AC16–AC20, AC22)


## Checkpoint evidence

- Final HTTP/startup/health/architecture suite: 144 tests passed on Python 3.14,
  no skips. Broader unit/architecture/controlled-provider/HTTP regression: 640
  passed, no skips. The final malformed-provider-config case was additionally
  covered in the 144-test focused rerun. Repository Ruff lint and format pass
  (226 files); strict mypy passes 76 source files; diff whitespace passes.
- AC2/AC4: controlled seeded personas complete HTTP redirects, bind verified local
  identities and obtain their current roles. Session output contains only user
  ID/email/role, original expiry and CSRF, excluding cookie/provider credentials,
  issuer/subject and protected analytical data. Actual email-based Cognito login
  remains Phase 5 live readiness.
- AC12–AC14/AC16: HTTP routes invoke application session checks before identity
  output; default expiry is one hour, no session read resets the cookie/lease,
  and the exact expiry boundary denies access. Attempt mismatch, expiry/replay
  and invalid callbacks create no session. Production __Host-/Secure and explicit
  loopback HTTP cookie modes have host-only HttpOnly/Lax cookies with absolute
  expiry; real browser reopening (AC15/browser portion of AC14) remains Phase 5.
- AC17/AC18: exact origin and session-bound CSRF protect valid-session logout;
  another session's CSRF fails. Logout denies replay of that session, preserves
  independent sessions and clears invalid sessions idempotently. Resolution or
  invalidation failures return generic 503 without clearing cookies or reporting
  success. Committed PostgreSQL behavior was separately proven in Phase 2.
- AC19/AC20: generic no-store errors cover 400/401/403/503, callback/provider errors,
  malformed/duplicate inputs and framework auth failures, without raw account,
  token, provider or database values. Callback query access logs are redacted.
  Malformed provider URL exceptions are sanitized before client construction.
  Live Cognito managed-login credential presentation remains Phase 5 evidence.
- AC22: enabled and disabled factories/imports were exercised in a fresh interpreter
  under socket/process/thread/provider/database/migration guards. Auth registration
  performs no external work; health works without dependencies and after explicit
  process-owned cleanup. Architecture fixtures reject direct route security,
  provider/database calls and inner-layer crypto imports; startup AST exceptions
  and existing negative fixtures remain intact. Only narrow logging/HTTP exception
  transport imports were added to the checker.
- The browser contract/UI handoff labels integration decisions as draft; no
  separate UI, token bridge, analytical/refresh product endpoints, live resource
  writes, deployment or provider-readiness claim was introduced. Concurrent
  Parquet edits briefly failed global lint/type checks, then were corrected by
  their ongoing work before inspection; this phase made no Parquet edits.
