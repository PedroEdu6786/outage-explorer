# Browser-to-Flask authentication contract

Status: **implemented and controlled-tested; integration choices remain draft**.
ADR-0046/0047 remain proposed. This records the Phases 4–5 implementation without
claiming approval of those ADRs, configured-provider readiness or deployment.
The separate UI and analytical/refresh endpoints are outside this phase.

Flask owns Authorization Code with PKCE S256, the callback and opaque application
sessions. Login credentials stay at Cognito. Browser code receives no provider
access/ID/refresh token and stores no credentials in localStorage. PostgreSQL
resolves the seeded identity and current single role; provider groups/scopes and
browser role labels cannot grant access.

## Routes

| Route | Request | Successful response |
| --- | --- | --- |
| `GET /api/auth/login` | Optional `return_to`, exactly one configured relative path | `302` to configured Cognito login; sets browser-binding cookie |
| `GET /api/auth/callback` | Provider `code` and `state`, matching binding cookie | `302` to configured UI origin plus stored allowlisted path; sets session cookie and clears binding cookie |
| `GET /api/auth/session` | Application session cookie | `200` identity, current role, original expiry and session-bound CSRF token |
| `POST /api/auth/logout` | Session cookie, exact permitted `Origin`, `X-CSRF-Token` | `204` only after committed current-session invalidation; clears session cookie |

The callback URI is the configured public backend origin plus
`/api/auth/callback`; the request Host never determines it. Paths are configured
as a comma-separated allowlist, default `/`, without query/fragment/encoded or
external destinations. Duplicate or malformed query values fail generically.
A callback mismatch, expired attempt, replay, invalid token or unlinked identity
creates no session. Provider callback errors clear the binding cookie and return
only a generic error, without echoing provider descriptions.

Session response:

```json
{
  "user": {"id": "seeded-user-id", "email": "seeded@example.test", "role": "viewer"},
  "expires_at": "2026-10-04T23:00:00+00:00",
  "csrf_token": "session-bound-opaque-value"
}
```

The public fields exclude issuer/subject, cookie credentials, provider tokens and
permission catalogs. Roles are `viewer`, `analyst`, `admin`. Session checks read
current PostgreSQL role assignments every time. Identity output does not replace
application authorization for later product data requests.

## Cookies and lifecycle

Production names are `__Host-outage_session` and `__Host-outage_login`, with
`Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/` and no Domain attribute. Explicit
loopback HTTP development uses `outage_session`/`outage_login` and omits Secure.
Both cookies use an absolute Expires rather than a sliding Max-Age. Session expiry
is establishment plus 3,600 seconds by default; login attempts expire after
600 seconds by default. The configured lifetime is fixed for each established
session and never extended by requests or browser reopening.

At or after expiry, sign in again through `/api/auth/login`. The backend retains
no provider tokens and performs no renewal. Cognito SSO may complete a new flow
without password re-entry; application expiry does not force provider-wide logout.
Controlled persistent-browser reopening is tested; real-provider browser readiness remains a Phase 5 gate.

Logout validates the origin and session-bound CSRF before invalidating a valid
session. A CSRF token from another session fails. Repeating logout with an invalid,
expired or revoked session clears that cookie after the origin check, without
changing other sessions. Store resolution/invalidation failures return `503`,
retain the cookie and never acknowledge successful logout. Independent browser
profiles have separate sessions; tabs sharing a cookie share its session.

## Origins, requests and errors

Prefer a same-origin UI development proxy forwarding `/api/` to Flask, including
Set-Cookie and the configured public callback route. This is a transport proxy,
not another credential/session owner. For separate **same-site** origins, configure
the UI origin explicitly and call fetch with `credentials: "include"`; send
`X-CSRF-Token` on logout using the value returned by the session route.

Only the exact configured backend/UI origins receive credentialed CORS headers;
there is no wildcard or reflection of arbitrary origins. Mutation requests require
one of those exact origins, including scheme and port. Permitted OPTIONS requests
allow GET/POST with X-CSRF-Token/Content-Type; other origins, methods or headers deny.
`Vary: Origin` and `Cache-Control: no-store` apply throughout auth responses.
CORS does not override SameSite=Lax: a cross-site UI needs a same-origin proxy or
a separately agreed transport change, rather than silently weakening cookies.

| HTTP status | Error code | Public message |
| --- | --- | --- |
| `400` | `login_failed` | Login failed |
| `400` | `invalid_request` | Invalid request |
| `401` | `unauthenticated` | Authentication required |
| `403` | `forbidden` | Access denied |
| `503` | `service_unavailable` | Service unavailable |

Errors use `{ "error": { "code": "...", "message": "..." } }` and include no
protected data or raw exception/provider/SQL text. Unknown or unsupported auth
route requests use generic `400 invalid_request`. Built-in Werkzeug access logs
redact URL queries; deployment/proxy/access-log configuration must also avoid
retaining callback codes/state or cookie/header credentials. Live Cognito invalid
credential presentation remains unverified by these controlled HTTP tests.

## Configuration and process lifecycle

`OUTAGE_AUTH_ENABLED=true` explicitly registers the routes. Without it, health-only
construction needs no credentials. Enabled auth requires:

- Shared explicit database modes: `OUTAGE_ACCESS_DATABASE_MODE` selects legacy
  `dsn` (default), `local`, `password`, or `iam`. DSN/local/password use
  `OUTAGE_ACCESS_DATABASE_DSN`; IAM uses trusted host/user/database/region/profile
  and CA settings detailed in [setup.md](setup.md). IAM signs afresh immediately
  before each new physical connection/retry; existing checkout does not sign.
  Migrations and seeded linkage are separate explicit operator commands.
- `COGNITO_ISSUER`, `COGNITO_DOMAIN`, `COGNITO_APP_CLIENT_ID`, explicit
  `COGNITO_OAUTH_SCOPES`; optional `COGNITO_RESOURCE` for the expected audience.
  Optional server-only `COGNITO_APP_CLIENT_SECRET` selects confidential HTTP Basic
  client authentication at the token endpoint; absent selects public PKCE. Empty
  or invalid confidential credentials fail without public fallback. Authorization
  URLs and browser payloads never contain the secret. Configured-provider
  behavior still requires real Phase 5 verification.
- `OUTAGE_AUTH_PUBLIC_ORIGIN`, `OUTAGE_AUTH_CALLBACK_URI`; optional
  `OUTAGE_AUTH_UI_ORIGIN` defaults to the public origin, including when blank.
- Optional `OUTAGE_AUTH_RETURN_PATHS` (default `/`),
  `OUTAGE_AUTH_SESSION_SECONDS` (default 3600, range 1–86400),
  `OUTAGE_AUTH_ATTEMPT_SECONDS` (default 600, range 1–3600) and
  `OUTAGE_AUTH_ATTEMPT_LIMIT` (default 1000, range 1–100000).
- `OUTAGE_AUTH_DEVELOPMENT_HTTP=true` is an explicit development-only setting;
  it requires loopback origins. Production origins use HTTPS and Secure cookies.

Configuration is read at startup; invalid enabled configuration fails before
network/database work. Imports/factories start no connection, migration, login,
refresh, worker or background thread. Health remains independent of dependencies.
Bootstrap owns lazy process-bound resources. Supervisors/tests may call
`app.extensions["outage_access_close"]()` at process shutdown; it is idempotent,
process-owned and also registered for normal interpreter exit. Do not call it
on request teardown or reuse a preconstructed auth app across forked processes.

See [Flask cookie API](https://flask.palletsprojects.com/en/stable/api/#flask.Response.set_cookie)
and [application factories](https://flask.palletsprojects.com/en/stable/patterns/appfactories/)
for framework behavior. The role matrix, fixed lease and seeded identity binding
are this application's contracts, verified through its own use-case tests.

## Reusable HTTP guards

`authenticated(access, transport)` passes `credential` and current `identity`
explicitly to a handler. `csrf_protected(access, transport)` checks exact origin
and application CSRF before passing `credential` and `csrf_validated`. Only
idempotent logout opts into invalid-session handling. `validated_request(parser)`
passes a plain typed `validated` query/JSON value. Authentication/origin guards
compose outside validation where denial must precede parsing. Parsers reject
duplicate/unsupported query values and malformed/duplicate/oversized JSON.

These helpers authenticate the HTTP boundary; downstream application use cases
must independently resolve current session validity and roles before every direct
and later-page protected operation. A previously authenticated identity does not
grant analytical or refresh access. No product endpoint or controller framework
is introduced by these reusable guards. See [verification.md](verification.md).
