# ADR-0046: Flask-owned login and opaque application sessions

Status: **Proposed — requires human approval**

Date: 2026-10-04

## Context

ADR-0018 selects Cognito identity and ADR-0045 fixes one-hour sessions without
automatic renewal. The user-access plan needs a concrete browser/session
integration without adding registration or Admin user management.

## Proposed decision

Use Flask-owned Authorization Code with PKCE (S256), bounded single-use
browser-bound login attempts, and trusted issuer/subject lookup against seeded
users. Verify Cognito access tokens through maintained libraries and discard
provider tokens after establishing the application session.

Use random 256-bit opaque cookie tokens with only their digests in PostgreSQL.
Join the current user role on each session resolution. Preserve immutable
establishment/expiry timestamps and invalidate only the current session on logout.
Use persistent host-only HttpOnly cookies, SameSite=Lax, production Secure and
the __Host- prefix. Mutation requests require session-bound CSRF and origin
checks. HTTP development transport must be explicitly selected.

This recommendation supports FR2, FR12–FR18 and TR1–TR4 without changing the
accepted monolith, seeded single-role access, or one-hour session boundary.
It does not claim deployed integration, provisioned accounts or live verification.

## Alternatives and consequences

- Browser-held provider tokens avoid application sessions but complicate
  current-session revocation and browser credential handling.
- A frontend credential bridge adds another identity/session owner without a
  present product need.

PostgreSQL availability becomes necessary for protected requests; fail closed
on storage failures. Transient PKCE material needs short retention, bounded
admission and explicit cleanup. Provider SSO is distinct from application logout.
