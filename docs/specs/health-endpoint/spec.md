# Spec: Project scaffold and health endpoint

Status: implementation scope requested by the user, 2026-10-01.

## Goal

Make the accepted layered Flask monolith runnable and demonstrate its dependency
direction with a small liveness use case and automated architecture checks.
Applies ADR-0028 and ADR-0030 without changing accepted boundaries.

## Requirements

- WHEN a caller requests `GET /health`, THE SYSTEM SHALL return HTTP 200 and
  JSON containing `status: "ok"`, `service: "outage-explorer"`, and `checked_at`
  as an ISO 8601 UTC timestamp. Authentication is not required for this probe.
- WHEN handling the probe, THE HTTP ROUTE SHALL invoke an injected application
  service and serialize its plain result. The service obtains time through an
  application-owned clock port implemented in infrastructure.
- WHEN constructing an application, THE BOOTSTRAP SHALL construct dependencies
  and pass the service to the HTTP factory. Imports and factory construction
  SHALL NOT start jobs, retrieve source data, or connect to external services.
- THE PROBE SHALL describe process liveness only, disclose no configuration or
  credentials, and perform no database, AWS, EIA, or analytical access.
- THE PROJECT SHALL install as a Python package and document reproducible setup,
  local startup, and quality commands. CI SHALL run lint, format, type checks,
  behavior tests, and architecture checks, including existing devlog tests.
- THE ARCHITECTURE CHECKS SHALL enforce the documented dependency matrix for
  absolute and relative imports, package re-exports, and narrow startup wiring.
  Negative fixtures SHALL demonstrate rejection of forbidden imports.

## Acceptance

1. The documented local command starts the API and `/health` meets its contract.
2. A fake clock allows testing the use case without Flask or cloud dependencies.
3. Separate app instances retain their injected dependencies. Factory creation
   does not invoke the health service or clock.
4. Wrong methods return 405; unknown routes return 404; HEAD has an empty body.
5. CI checks the actual source tree and proves rejection of invalid fixtures.

## Limits

A green probe does not establish database readiness, authorization correctness,
query isolation, or publication safety. Those require future use cases and
behavior tests. No database schema/driver, runtime topology, production WSGI
server, container deployment, or source contract is selected by this scaffold.
