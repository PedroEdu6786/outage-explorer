# ADR-0076: Auth and query transport request models

Status: **Accepted by explicit user direction** (October 12, 2026)

## Context

The user requested strict application of ADR-0075 to the datasets, access and
queries controllers. Existing auth request objects were dataclasses and query
parsers returned positional tuples. The import checker allowlists third-party
validation APIs even in HTTP adapters.

## Decision

Use strict, frozen Pydantic DTOs for these transport inputs. Keep them in the
HTTP layer because application services continue accepting their existing
transport-independent arguments. Permit only these additional imports:

- `entrypoints/http/schemas.py`: `BaseModel`, `ConfigDict`.
- `entrypoints/http/query_requests.py`: `BaseModel`, `ConfigDict`, `Field`,
  `ValidationError`, `field_validator`.

The query DTOs validate SQL text bounds and pagination fields, never SQL syntax
or references. SQL inspection stays in the bounded subprocess. HTTP decoding,
JSON envelope checks, duplicate detection and lexical integer parsing remain
transport adapter responsibilities. No inner-layer import rules change.

Use `respond_with(JsonPayloadResponse)` for existing public catalog, preview and
query payloads, and `respond_with(SessionResponse)` for the identity allowlist.
Use dedicated `respond_with_auth` DTOs for login/callback redirects and cookies,
and bodyless logout. Keep callback failure cleanup in the central error handler.

Authentication precedes request validation. Query and catalog application
services retain fresh authorization; this does not extend request-scoped access
exceptions. Login/callback stay public. Logout retains its CSRF guard's explicit
invalid-session exception and revokes only a validated live session.

## Consequences

Controllers no longer parse or construct HTTP responses. Session and logout
now apply the required empty-request decorator, rejecting unexpected query
parameters and bodies with 400 after the applicable guard. Existing successful
responses, cookie rules and preflight policies remain unchanged. Architecture
fixtures constrain both the new APIs and their allowed module locations.
