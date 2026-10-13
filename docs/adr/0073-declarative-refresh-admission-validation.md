# ADR-0073: Validate refresh admission with Pydantic through a decorator

Status: **Accepted by explicit user direction** (October 12, 2026)

## Context

The user requested moving refresh admission validation out of the controller,
using Pydantic and a decorator like the existing request-validation flow.
The admission DTO previously validated key length and characters manually.

## Decision

Use the existing `validated_request` decorator after CSRF and Admin guards.
Its transport adapter checks the bounded JSON envelope and forbidden query/body
fields, then constructs `application/refresh_request.py`'s strict, frozen
Pydantic `RefreshAdmissionRequest`. The controller receives the validated DTO
and calls the service. No validation occurs in the admission handler or service.

The model declares a required ASCII key of 16–128 letters, digits, underscores
or hyphens, forbids extra fields and coercion, and translates validation errors
through `parse` to the existing application `InvalidRequestError`. Direct
callers use the same model with keyword arguments. Invalid direct construction
raises Pydantic `ValidationError`; `parse` provides application error translation.

Extend ADR-0030's library boundary narrowly to permit only `BaseModel`,
`ConfigDict`, `Field` and `ValidationError` from Pydantic in this module.
Architecture tests constrain the exception. Existing ADR-0066 access semantics,
HTTP contracts, idempotency and refresh execution remain unchanged.

## Consequences

Validation is declarative and reusable outside HTTP. Transport decoding,
duplicate-key detection, media type and size bounds remain HTTP responsibilities.
The existing decorator is reused without introducing a framework or a second
validation mechanism. Refresh status/latest refactoring is outside this change.
