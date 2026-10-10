# ADR-0066: Authorize refresh once and pass request-scoped access

Status: **Accepted** (explicit user direction, October 10, 2026)

## Context

Refresh POST resolved the same session in the CSRF guard, the Admin role guard,
and the application service. Refresh status reads also repeated authorization
after their route guard. The user directed using the identity established by
the decorators rather than authorizing again inside the refresh use case.

## Decision

For refresh HTTP operations, resolve the application session once per request
through `AccessService`. A successful CSRF check returns immutable `RequestAccess`
containing the server-resolved principal. The role decorator checks that same
snapshot and passes it explicitly into the route and refresh service. GET guards
authenticate freshly themselves because they have no CSRF guard.

`RefreshService.admit`, `status` and `latest` require this already-approved access
context instead of a session token. They do not repeat session resolution or role
authorization. Admission uses its principal ID for idempotency and requester
metadata. Non-HTTP callers must obtain fresh Admin access through
`RefreshService.authorize(token)` before invoking a use case.

This supersedes the requirement to reauthorize *inside* these refresh methods;
application-owned `AccessService` still establishes identity and checks roles
before parsing and refresh storage access. Other use cases retain their existing
authorization boundaries.

## Consequences

- Refresh POST performs one session lookup shared by CSRF and role checks.
- Every new HTTP request authenticates again, observing expiry, revocation and
  current application role; there is no cross-request authorization cache.
- `RequestAccess` is a trusted internal DTO, not a signed credential. Never
  construct it from browser claims, accept it from JSON, or reuse it across
  requests. Internal callers are responsible for entering through authorization.
- Role/revocation changes after the request's lookup are observed on the next
  request. A second lookup in the same request is deliberately eliminated.
- No Flask globals enter application code. Worker lease/publication ownership,
  session cookie transport, CSRF proof and PostgreSQL idempotency stay unchanged.
