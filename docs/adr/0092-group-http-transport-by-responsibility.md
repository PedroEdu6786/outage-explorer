# ADR-0092: Group HTTP transport files by responsibility

Status: **Accepted by explicit user direction** (October 12, 2026)

## Context

After moving analytical argument parsing into the CLI layer, HTTP request
schemas, validation helpers, guards, transport handling and response DTOs
remained scattered directly under `entrypoints/http/`. The user requested a
coherent organization for those files. ADR-0076 had reviewed Pydantic imports
at two exact HTTP module paths, so a path change must keep that exception narrow.

## Decision

Keep one HTTP entrypoint layer and its existing controller pattern. Place
request decoding and DTOs in `entrypoints/http/requests/`, response DTOs and
serialization in `entrypoints/http/responses/`, and guards, browser transport,
error handling and preflight in `entrypoints/http/transport/`. Controllers remain
in `routes/`; `app.py`, process startup, `data_services.py` and `openapi.json`
remain at the HTTP root. Move identity serialization out of the auth request
module into the auth response module.

ADR-0076's reviewed Pydantic imports now apply only to
`entrypoints/http/requests/auth.py` (`BaseModel`, `ConfigDict`) and
`entrypoints/http/requests/query.py` (`BaseModel`, `ConfigDict`, `Field`,
`ValidationError`, `field_validator`). This supersedes only the two module
locations recorded in ADR-0076; every allowed API and validation boundary stays
the same. Keep the architecture check's negative fixtures at the new paths.

## Consequences

Internal Python imports and architecture fixtures use the new paths. The HTTP
routes, request and response shapes, authorization order, startup path and
process ownership do not change. This is a package organization change within
the accepted layered monolith, not a new service or transport framework.
