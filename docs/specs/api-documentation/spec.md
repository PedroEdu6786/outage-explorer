# API documentation

Serve Swagger UI at `GET /api/docs` (redirecting to `/api/docs/`) and the full
OpenAPI 3.1 contract at `GET /api/openapi.json`. Both are available without
authentication or external resources, including in health-only configuration.
The contract documents all implemented health, auth, data and documentation
operations, including request parameters, schemas, errors and session/CSRF rules.
Documenting optional endpoints does not enable them.

Use the pinned flask-swagger-ui dependency and its locally packaged assets.
Package the full contract inside `entrypoints/http/openapi.json` so installed
wheels do not depend on repository documentation paths. Preserve the frozen
data-only client handoff contract; parity tests detect divergence of its operations
and schemas. Tests compare the full contract against the fully enabled Flask
route map, check documentation/assets without services, and verify local cookie
names remain specific to each app instance.

Swagger uses the browser's existing HttpOnly session after browser login. Obtain
the CSRF token from the session operation and supply it on mutations alongside
the exact configured Origin. Mutation buttons execute real operations, including
refresh and logout. Disable Swagger's external validator; no external UI CDN is
needed. Provider and analytical readiness remain separate checks.
