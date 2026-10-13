# ADR-0083: Pass request-scoped catalog access to the service

Status: **Accepted by explicit user direction** (October 12, 2026)

## Context

The catalog controller authenticated a session, then `CatalogService.list`
resolved the token again to choose datasets and called `authorize`, causing
another lookup before reading publication metadata. The user directed that the
controller resolve the token and pass approved data to the service.

## Decision

The catalog route composes `roles_required`, `catalog_required` and
`validated_request`, in that order. The role guard authenticates once through
application-owned `AccessService`; the catalog guard asks that same service to
select public datasets and verify their analytical scope. It passes immutable
`CatalogAccess` into `CatalogService.describe`. The service accepts that approved
context and reads publication metadata without receiving a token or resolving
the session again.

Non-HTTP callers must freshly call `AccessService.authenticate(token)` and
`AccessService.require_catalog(request_access)` before calling the catalog
service. `CatalogAccess` is an internal trusted value, never parsed from browser
input or reused across requests. This extends the request-scoped access pattern
of ADR-0066 and ADR-0070 to catalog only; query authorization is unchanged.

## Consequences

The catalog request performs one session lookup. Revocation and role changes
take effect on the next request. Authentication and catalog scope checks precede
input validation and publication access. Dataset selection stays in the
application access policy; the controller only composes guards and invokes the
service.
