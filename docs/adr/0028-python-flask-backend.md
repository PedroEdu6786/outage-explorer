# ADR-0028: Use Python and Flask for the backend

Status: **Accepted by user direction**

Date: 2026-10-01

Supersedes: [ADR-0004](0004-python-fastapi-backend.md).

## Context and decision

The user requested a clean architecture with Flask and the already selected
tools. Use Python with Flask for the HTTP API. Keep the existing data,
authentication, operational storage, and hosting selections.

No backend implementation exists to migrate. ADR-0004 remains as the historical
record of the earlier FastAPI choice; current documentation points here.

## Options considered

- Keep FastAPI: consistent with the earlier plan, but does not follow the
  user's current framework direction.
- Use Flask: follows the current request and supports a thin HTTP adapter
  around framework-independent application services.

## Consequences

Use an application factory and Blueprints for HTTP composition. Choose explicit
request/response validation, OpenAPI tooling, and a production WSGI server
during implementation. Background refresh and isolated analytical execution
need application-owned lifecycles outside request handling.

The [architecture comparison](../specs/outage-explorer-backend/architecture-options.md)
recommends a modular monolith with ports and adapters. That structural proposal
is recorded separately in ADR-0029 and is not implicitly accepted by choosing Flask.

## References

- [Flask application factories](https://flask.palletsprojects.com/en/stable/patterns/appfactories/)
- [Flask Blueprints](https://flask.palletsprojects.com/en/stable/blueprints/)
- [Flask background-task limitations](https://flask.palletsprojects.com/en/stable/async-await/)
