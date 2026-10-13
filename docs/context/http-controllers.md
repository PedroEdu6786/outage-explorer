# Required HTTP controller pattern

This is the mandatory convention for new controllers and controller refactors.
It records the user's explicit direction in
[ADR-0075](../adr/0075-decorator-driven-http-controllers.md). Agents must read this
before adding or changing a controller. The reference implementation is
[`routes/refresh.py`](../../src/outage_explorer/entrypoints/http/routes/refresh.py).

## Must do

1. Declare authentication, roles, dataset access and CSRF through the appropriate
   existing decorators. Apply only the guards required by the endpoint contract:
   public login/health endpoints do not become authenticated, and read-only GETs
   do not acquire mutation CSRF requirements.
2. Declare request validation with `@validated_request(...)`. Decode bounded HTTP
   inputs in a transport adapter and construct a validated request DTO. Use
   Pydantic for structured request field constraints and cross-field validation.
   Reuse existing reviewed DTOs; additional inner-layer Pydantic APIs/modules must
   follow the repository's narrow import-exception process.
3. Validate even endpoints with no query/body inputs: use
   `@validated_request(empty_request)`. For path parameters, pass their names via
   `route_parameters=(...)` and inject the validated result. The current status
   adapter returns a validated string; an empty request needs no artificial DTO.
4. Declare JSON response mapping with `@respond_with(ResponseDto)`. Every new or
   refactored JSON controller must use its response DTO rather than building the
   response in the handler.
5. Keep the handler focused on invoking the application use case with approved
   access and validated inputs, then returning its result. Keep domain decisions,
   storage access, SDK calls and runtime wiring out of controllers.
6. Register blueprints and shared HTTP handling centrally in `create_app`.
   Add the endpoint's preflight policy in `preflight.py` where credentialed CORS
   applies. Register new error policies centrally in `errors.py` as needed.
7. Preserve application authorization boundaries. Guards invoke application-owned
   access checks; this convention does not extend ADR-0066/0070's request-scoped
   access exceptions to other use cases or remove their existing checks.

For a new endpoint, these are implementation requirements, not optional cleanup
or a reason to ask the user to approve decorators again. Ask only when the
endpoint's access policy or HTTP contract is genuinely unspecified.

## Required decorator order

```python
@blueprint.post("/api/refresh")
@csrf_protected(access, transport)
@roles_required(access, transport, "admin")
@validated_request(refresh_admission_request)
@respond_with(RefreshAdmissionResponse)
def admit(
    *,
    request_access: RequestAccess,
    validated: RefreshAdmissionRequest,
    **_: object,
) -> object:
    return services.refresh.admit(request_access, validated)
```

The route decorator registers the wrapped function. At request time, guards run
before input parsing; the request decorator supplies validated data; the response
decorator invokes the handler and maps its result. For preview, place
`dataset_required(access)` after the role guard and before request validation.
Do not move parsing ahead of authentication or authorization.

No-input and path-input reads follow the same pattern:

```python
@blueprint.get("/api/refresh/latest")
@roles_required(access, transport, "admin")
@validated_request(empty_request)
@respond_with(RefreshLatestResponse)
def latest(*, request_access: RequestAccess, **_: object) -> object:
    return services.refresh.latest(request_access)


@blueprint.get("/api/refresh/<run_id>")
@roles_required(access, transport, "admin")
@validated_request(refresh_status_request, route_parameters=("run_id",))
@respond_with(RefreshStatusResponse)
def status(*, request_access: RequestAccess, validated: str, **_: object) -> object:
    return services.refresh.status(request_access, validated)
```

## Must not do: former patterns and their replacements

The following examples document patterns that must not be copied or reintroduced.

| Must not do in a controller | Must do instead |
| --- | --- |
| `admission = refresh_admission_request()` | Inject the DTO with `@validated_request(refresh_admission_request)`. |
| `parameters(set())` | Declare `@validated_request(empty_request)` or include the check in the endpoint's transport adapter. |
| `identifier(run_id)` or manual input checks | Validate the named route parameter through the request decorator. |
| Inline session, role, dataset or CSRF checks | Use the appropriate authorization decorators, preserving application-owned policy checks. |
| Handwritten DTO key-length/character loops | Declare Pydantic field constraints, as in `RefreshAdmissionRequest`. |
| `jsonify(...)`, `Response(...)`, response dictionaries or status/header assignments | Return the service result and use `@respond_with(ResponseDto)` for JSON responses. |
| `return RefreshAdmissionResponse.from_result(run).build()` | Let `respond_with` invoke the DTO factory and builder. |
| `if run is None: ...` to build a 404 or an empty response envelope | Encode the endpoint's missing-result presentation in its response DTO. |
| `@blueprint.errorhandler(Exception)` forwarding to a shared mapper | Register error handling once through `register_error_handlers`. |
| `@blueprint.before_request` checking for OPTIONS | Register preflight once through `register_preflight_handler`. |
| `request.path == "/api/refresh"` to select preflight methods | Use an explicit endpoint-name `PreflightPolicy`. |
| Per-controller `try/except` to serialize exceptions | Allow exceptions to reach the centralized error handlers. |

Transport adapters may still reject malformed JSON, duplicate/unknown query
parameters, media types, encodings and oversized transport inputs. These are
transport checks; they must not return to controller bodies. Pydantic validates
structured DTO values, not Flask's request lifecycle. Keep application business
validation in its proper use case/domain layer.

## Response DTO contract

`entrypoints/http/responses.py` owns `respond_with`, `ResponseDTO` and
`ResponseData`. A response DTO implements:

- `from_result(result)`: construct public response data from the service result.
- `build()`: return `ResponseData(body=..., status=..., headers=...)`.

`status` defaults to `200`; headers default to empty. Only the generic decorator
calls `jsonify`, sets the status and applies those headers. DTOs must not build
Flask responses themselves. Endpoint-specific rules such as admission's active
`202` versus terminal `200`, `Location`, `Retry-After`, latest's `run` envelope
and status's missing-run `404` belong in the DTO.

Pure public projections can live in `application/`, as the refresh result bases
do. Flask, HTTP serialization and header handling stay in `entrypoints/http/`.
Do not expose private service/domain fields by blindly serializing whole objects.
Exceptions from handlers or DTO mapping propagate to the shared error handling;
the generic decorator must not suppress them.

## Central blueprint registration and HTTP policies

Blueprint factories still declare their routes and receive injected services.
“Centralized” means their registration and shared transport policies live in
`app.py`, not that every route moves into one giant blueprint.

`create_app` registers `register_error_handlers(app, auth_transport)` and
`register_preflight_handler(app, auth_transport, PREFLIGHT_POLICIES)` once for
configured auth/data HTTP. It also registers the blueprints. There are no
per-controller exception or preflight hooks.

`errors.py` preserves sanitized data/auth mappings, login/callback behavior and
callback attempt-cookie cleanup. `preflight.py` assigns methods/header allowances
to exact endpoint names. OPTIONS must not invoke guards or services; actual
requests must still authenticate and authorize normally. Unmatched URLs proceed
to routing-error handling. Shared finalization continues to add security/CORS
headers on successes and errors.

Preserve existing policies unless the user requests a contract change: auth and
query preflight allow GET/POST; dataset endpoints allow GET; refresh admission
allows POST and refresh reads allow GET. All three refresh endpoints currently
allow `Idempotency-Key`. Moving policies is not permission to change allowances.

## Scope, existing routes and review checks

Refresh, datasets, queries and access now follow this convention. Catalog,
preview and query results already contain public application payloads and use
`JsonPayloadResponse` without another envelope. Session uses `SessionResponse`
to project the identity allowlist. Apply the same convention to future changes;
other endpoints, such as health and documentation, retain their explicit contracts.

`respond_with` currently supports JSON bodies. Login redirects, cookie transport,
streaming and bodyless responses require their existing specialized handling;
do not force them through `jsonify` or change their contracts. If refactoring
these flows, use dedicated transport handling rather than expanding application
DTOs with Flask dependencies. Access uses `respond_with_auth` with login, callback
and logout DTOs. Callback binding is supplied through the request adapter. The
logout response decorator wraps `logout_if_authenticated`, which skips revocation
only for the outer CSRF guard's explicitly permitted invalid-session outcome;
origin, live-session CSRF and store failures still reach centralized errors.
Session and logout use `empty_request`, rejecting unexpected query/body inputs.
Public health/documentation routes retain their explicit access contracts.

Auth and query transport Pydantic models have exact API/module allowances in
[ADR-0076](../adr/0076-auth-and-query-transport-request-models.md). This adds no
inner-layer framework allowance and does not move SQL inspection into HTTP.

Before finishing a controller change, verify guard-before-validation ordering,
invalid-input rejection before service calls, exact response envelopes/statuses/
headers, missing-result behavior, sanitized failures, and preflight policies.
Check callback cookie cleanup if auth changes. Run relevant HTTP tests, import
boundary tests, Ruff and mypy; report what actually ran. Static checks alone do
not prove these controller conventions: the checklist also requires code review.
