# ADR-0075: Require decorator-driven HTTP controllers

Status: **Accepted by explicit user direction** (October 12, 2026)

## Context

The user requested removing validation, response construction, exception hooks
and preflight hooks from controllers, approved their replacements, and directed
that the resulting pattern become mandatory guidance for agents across controllers.

## Decision

Adopt [Required HTTP controller pattern](../context/http-controllers.md) for new
controllers and controller refactors. Use explicit auth/role/CSRF/dataset guards
as required by the endpoint contract, followed by request-validation decorators
and response DTO decorators. Structured request DTOs use reviewed Pydantic
validation; JSON responses use `respond_with(ResponseDto)`. Handlers pass approved
access and validated inputs to application use cases and return their results.

Centralize blueprint registration, exception handling and endpoint-based
preflight policies in HTTP setup. Do not reintroduce inline controller validation,
JSON/status/header assembly, exception serialization or local preflight hooks.
The living guide records the former forbidden patterns and their replacements.

This refines ADR-0030's thin-entrypoint convention and builds on ADR-0066,
ADR-0070, ADR-0071 and ADR-0073. It does not widen their authorization or Pydantic
exceptions, alter API/CORS contracts, or permit Flask in application/domain code.

## Consequences

Controllers express policy declaratively and share transport plumbing. Response
DTOs retain endpoint-specific public mapping while generic serialization remains
central. Endpoint additions require explicit preflight/error policy consideration
and behavioral verification. Refresh is the reference; remaining legacy endpoints
are migrated when refactored, not treated as compliant merely because they exist.
Non-JSON flows retain specialized transport behavior until separately refactored.
