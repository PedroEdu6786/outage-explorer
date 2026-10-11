# ADR-0070: Authorize preview in controller guards

Status: **Accepted by explicit user direction** (October 10, 2026)

## Context

The user rejected service-level `_authorize` and directed using the existing
controller authentication/authorization decorators, as refresh already does.
Preview must still check current roles and dataset scope on every request.

## Decision

The preview controller composes `roles_required`, `dataset_required` and
`validated_request`, in that order. The existing role guard authenticates once
through `AccessService`; the dataset guard asks that same application service to
approve the requested public dataset using the established `RequestAccess`.
Unknown and forbidden datasets both yield `dataset_unavailable` before parsing.

The dataset guard passes immutable `PreviewAccess` (principal plus approved
dataset) explicitly into the controller. `PreviewService.read` receives that
context and a validated request; it has no access-service dependency, token
argument, `_authorize` or `page` method. Each HTTP continuation enters the guards
again. Snapshot/cursor ownership checks still belong to the sequence store.

Non-HTTP callers must call `AccessService.authenticate(token)` and then
`require_dataset(context, dataset_id)` freshly before invoking preview.
`PreviewAccess` is a trusted internal DTO; never construct it from browser claims
or reuse it across requests. This extends ADR-0066's request-scoped access pattern
to preview and supersedes the requirement for a second check inside preview.
Other analytical use cases retain their current authorization contracts.

## Consequences

One session lookup per HTTP preview, including continuations. Role changes and
revocation take effect on the next request. Authentication and dataset access
errors precede malformed filter errors. No Flask context enters the application.
