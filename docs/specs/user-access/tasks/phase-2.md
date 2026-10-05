# Tasks: Provider verification and fixed sessions
> Status: complete · Slug: user-access · Plan: ../plan.md · Spec: ../spec.md

## Phase 2: Provider verification and fixed sessions (plan phase 2)

- [x] **T2.1** [P] Create security-material adapter for random 256-bit credentials, digests, PKCE S256 and session-bound CSRF validation — `src/outage_explorer/infrastructure/security.py`; never expose verifier/token values through representations or logs. Requires T1.C; independent of T2.2. (FR12, FR13, FR17, TR1, TR2)
- [x] **T2.2** [P] Create Cognito authorization/code-exchange and access-token verification adapters with trusted issuer/client configuration, bounded JWKS retrieval/cache/rotation and redacted errors — `src/outage_explorer/infrastructure/cognito/identity.py`; validate signature/algorithm, issuer, access purpose, expiry and expected client/resource, discard all token responses after identity verification and expose no refresh/global-sign-out behavior. Requires T1.C; independent of T2.1. (FR2, FR5, FR6, FR19, TR1–TR3)
- [x] **T2.3** Create login orchestration with allowlisted destinations, browser-bound expiring state and single atomic attempt consumption before external exchange, then verified issuer/subject lookup and fixed session creation — `src/outage_explorer/application/services/login.py`. Depends on T2.1, T2.2; no transaction spans provider calls, no implicit user creation or caller/provider role acceptance. (FR2, FR5, FR6, FR13, FR18, FR19, TR1–TR3)
- [x] **T2.4** Create session resolution/current identity and current-session logout service with injected clock, fresh role lookup and committed digest-specific invalidation — `src/outage_explorer/application/services/access.py`; preserve original expiry, deny exactly at expiry and on store failure, retain independent sessions, and never acknowledge failed invalidation as logout success. Depends on T2.3. (FR4–FR6, FR12–FR18, TR2, TR3)
- [x] **T2.5** Create fake-port lifecycle tests for identity binding, generic failures, role spoofing, attempt mismatch/expiry/replay, expiry boundary/activity, independent sessions and logout failures — `tests/unit/test_user_access_sessions.py`; verify no refresh call, retained provider token or provider global logout. Depends on T2.4. (FR2, FR4–FR6, FR13–FR19, AC2, AC4–AC6, AC13, AC14, AC16–AC19, AC22)
- [x] **T2.6** Create controlled provider/JWKS integration tests for PKCE exchange, wrong token purpose/signature/issuer/client, expiry, key rotation, bounded failures and sanitized outputs — `tests/integration/test_cognito_identity.py`; use controlled transports, not real accounts. Depends on T2.2, T2.5. (FR2, FR5, FR19, AC2, AC5, AC6, AC19)
- [x] **T2.7** Extend real PostgreSQL lifecycle tests for two sessions, atomic attempt replay, concurrent post-logout checks and database failures — `tests/integration/test_user_access_postgresql.py`; assert logout success only after committed invalidation and unchanged original expiry. Depends on T2.4, T2.6. (FR12–FR18, AC13, AC14, AC16–AC18)
- [x] **T2.C** Checkpoint: run the lifecycle/provider/PostgreSQL suites plus Ruff, mypy and architecture checks — `tests/unit/test_user_access_sessions.py`, `tests/integration/test_cognito_identity.py`, `tests/integration/test_user_access_postgresql.py`, `docs/specs/user-access/tasks/phase-2.md`; verify seeded binding/current identity, fixed expiry/no renewal, replay denial and isolated logout without connector access. Depends on T2.7. (AC2, AC4–AC6, AC13, AC14, AC16–AC19, AC22)


## Checkpoint evidence

- Focused lifecycle/provider/PostgreSQL/setup/architecture run: 153 tests passed,
  no skips, Python 3.14 and disposable loopback PostgreSQL 18.6. Ruff lint and
  format checks pass repository-wide; strict mypy passes 72 source files.
- AC2/AC4–AC6: fake seeded personas establish sessions from verified issuer/subject;
  current identity reads fresh local roles, rejecting unknown/unassigned identities.
  Controlled signed Cognito responses discard groups/roles and access/ID/refresh
  tokens; email is never used to link identities. Actual persona email login
  against configured Cognito remains Phase 5 readiness evidence.
- AC13/AC14/AC16: expiry is exactly establishment plus one hour, untouched by
  activity/resolution, denied exactly at expiry, with no renewal/refresh capability.
  Token validity is checked only to establish the independent application lease.
- AC17/AC18: atomic attempt consumption rejects binding/state mismatch, expiry and
  replay before exchange. Two independent sessions remain isolated; eight concurrent
  post-commit checks reject the logged-out session and accept the other. A deferred
  PostgreSQL COMMIT failure rolls back invalidation and raises a store failure
  rather than logout success; unavailable stores fail closed.
- AC19: malformed/purpose/signature/issuer/client/resource/expiry/provider failures
  return generic sanitized login failures. Controlled transports cover PKCE S256,
  bounded response/key/cache/rotation handling, error/redirect/timeout rejection,
  log sanitization and token disposal. Provider-side invalid-credential presentation
  is unverified until Phase 5 live smoke.
- Phase 2 portion of AC22 passes without connector, analytical data, AWS accounts,
  RDS writes or Cognito provisioning. HTTP/browser persistence and role-policy
  integration remain later phases; ADR-0046/0047 retain proposed status.
- Full regression with the disposable PostgreSQL DSN: 937 tests and 17 subtests
  passed in 241.82 seconds, no skips. Dependency consistency and sdist/wheel
  build passed; the wheel contains the new login/access/security/Cognito modules.
