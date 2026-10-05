# User-access operator setup

The auth implementation is available for configured local use. Controlled
PostgreSQL/provider/browser tests establish behavior; [verification.md](verification.md)
records actual checks and the still-pending real login gates. This runbook itself
performs no deployment, cloud provisioning, password change or RDS write.

## Database authentication

HTTP and explicit `access-setup` share these settings. Setup requires no Cognito
configuration. Runtime credentials should have only application privileges;
use separately supplied setup credentials for migrations and seeding. Do not
run setup automatically at import, application construction or HTTP requests.

| Setting | Meaning |
| --- | --- |
| `OUTAGE_ACCESS_DATABASE_MODE` | `dsn` (legacy default), `local`, `password`, or `iam` |
| `OUTAGE_ACCESS_DATABASE_DSN` | Required for DSN/local/password; explicit host required. Local mode accepts loopback or a Unix socket; password mode requires an explicit DSN password. Remote targets require `sslmode=verify-full`. Hidden in representations/errors. |
| `OUTAGE_ACCESS_DATABASE_HOST` | IAM: trusted actual RDS endpoint ending in `.rds.amazonaws.com`; do not use a custom DNS alias |
| `OUTAGE_ACCESS_DATABASE_PORT` | IAM: optional, default `5432` |
| `OUTAGE_ACCESS_DATABASE_NAME` | IAM: explicit existing database |
| `OUTAGE_ACCESS_DATABASE_USER` | IAM: explicit PostgreSQL user with IAM authentication |
| `OUTAGE_ACCESS_DATABASE_REGION` | IAM: signing region |
| `OUTAGE_ACCESS_DATABASE_PROFILE` | IAM: optional local profile; absent selects AWS's runtime credential chain |
| `OUTAGE_ACCESS_DATABASE_SSLROOTCERT` | IAM: trusted local RDS CA bundle path; TLS always uses `verify-full` |

IAM fields and DSN configuration cannot be mixed, including empty supplied values.
The enabled HTTP parser rejects malformed modes before any external work. The
legacy DSN form remains supported; a startup-generated IAM token inside a DSN
is not a reconnect strategy. Use explicit IAM mode for runtime IAM connections.

Example nonsecret local IAM configuration (supply your actual endpoint/CA path):

```sh
export OUTAGE_ACCESS_DATABASE_MODE=iam
export OUTAGE_ACCESS_DATABASE_HOST=database.cluster.example.us-east-1.rds.amazonaws.com
export OUTAGE_ACCESS_DATABASE_NAME=outage-explorer-db
export OUTAGE_ACCESS_DATABASE_USER=outage_app
export OUTAGE_ACCESS_DATABASE_REGION=us-east-1
export OUTAGE_ACCESS_DATABASE_PROFILE=outage-explorer
export OUTAGE_ACCESS_DATABASE_SSLROOTCERT=/trusted/path/global-bundle.pem
```

The current retained local profile name is `outage-explorer`. Read-only October 5
revalidation found it still resolves to root; it was not replaced. Production
identity/privileges remain deployment inputs. EC2 provisioning and changing this
local identity do not block independent local implementation/testing.

The pool signs a fresh 15-minute IAM connection credential immediately before
every new physical connection, including failed attempts/retries. Existing
connection checkout performs no signing. Tokens are not stored in a shared DSN,
cache or application DTO. Credential lookup/refresh/signing runs in a disposable
spawned process with a three-second deadline; timed-out children are terminated.
No credentials, subprocess, connection or thread is acquired at construction.
Pool size is four, queue capacity sixteen, checkout/connect/reconnect waits are
three seconds, statement timeout five seconds and lock timeout one second.
Driver/SDK errors are sanitized before pool retry logging. Process resources must
be constructed after a fork and closed through the app's idempotent shutdown hook.
Credential refresh cannot change application expiry or renew Cognito tokens.

See [AWS IAM authentication](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.html)
and [RDS PostgreSQL TLS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html).

## Cognito and browser origins

Enable routes with `OUTAGE_AUTH_ENABLED=true`; health-only construction needs no
provider or database settings. Set `COGNITO_ISSUER`, `COGNITO_DOMAIN` (HTTPS, no
trailing slash), `COGNITO_APP_CLIENT_ID`, and explicit space-separated
`COGNITO_OAUTH_SCOPES`. Optional `COGNITO_RESOURCE` selects the expected audience.
Supply `COGNITO_APP_CLIENT_SECRET` securely on the server for confidential clients;
its presence selects HTTP Basic token-endpoint authentication. Empty secrets fail
configuration; a wrong secret fails generically with no public-client fallback.
An absent secret selects public PKCE. Both retain Authorization Code with S256
PKCE. Neither retains nor renews access, ID or refresh tokens; no global sign-out
is performed. Never put secrets in frontend environment variables, manifests,
authorization URLs, logs, terminal history or source control. The existing live
client is confidential, so it needs the secret even though public clients are
supported by controlled tests.

Set exact `OUTAGE_AUTH_PUBLIC_ORIGIN`, `OUTAGE_AUTH_CALLBACK_URI`, optionally
`OUTAGE_AUTH_UI_ORIGIN` (defaults to public origin), and comma-separated
`OUTAGE_AUTH_RETURN_PATHS` (defaults to `/`). Register the exact public URI
`<public-origin>/api/auth/callback` in Cognito. The request Host does not select it.
Choose origins with scheme and port, no path/query/fragment; return paths are
allowlisted relative paths without query, fragment, encoding or external URLs.

Prefer a same-origin UI proxy forwarding `/api/`, callbacks and Set-Cookie to
Flask. The configured public origin is the browser-facing proxy, not a hidden
backend listen address. For separate same-site UI/backend origins, use exact
credentialed CORS and `fetch(..., {credentials: 'include'})`. Return the session's
CSRF value as `X-CSRF-Token` on logout with an exact allowed Origin. CORS does not
make cross-site SameSite=Lax cookies work; use a same-origin proxy for that case.
Explicit `OUTAGE_AUTH_DEVELOPMENT_HTTP=true` accepts only loopback origins and
non-Secure development cookie names. HTTPS production uses host-only
`__Host-` cookies with Secure, HttpOnly, SameSite=Lax and `/` scope.

`make run` loads the existing gitignored `.env` via Flask CLI; direct factories
and `access-setup` do not load dotenv. Export settings into the current command
process explicitly. Variables in another terminal are not automatically visible.

See the [HTTP contract](http-contract.md) for exact response/error/logout shapes
and [Cognito token endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html).

## Explicit trusted setup

The read-only October 5 check found the existing application schema and all three
trusted Viewer/Analyst/Admin bindings in `outage-explorer-db`, with runtime user
`outage_app`. The local legacy PGUSER/PGDATABASE values do not match these targets.
Do not rerun cloud setup simply because this guide exists. All three provider
accounts still require their first-login password changes, which remain live work.

After explicit authorization for a new target, configure separate setup privileges
and run these commands; they make database changes:

```sh
.venv/bin/python -m outage_explorer.entrypoints.cli.access_startup --help
.venv/bin/python -m outage_explorer.entrypoints.cli.access_startup migrate
.venv/bin/python -m outage_explorer.entrypoints.cli.access_startup seed --manifest /trusted/personas.json
.venv/bin/python -m outage_explorer.entrypoints.cli.access_startup cleanup
```

Migrations serialize with a PostgreSQL advisory transaction lock and rollback DDL
and revision state together. Manifest validation precedes database/signing work.
A trusted reviewed JSON array contains only `identity_issuer`, `identity_subject`,
`email`, and one `role` (`viewer`, `analyst`, `admin`) per record. Example synthetic
record: `{"identity_issuer":"https://trusted.test/pool","identity_subject":"viewer-subject","email":"viewer@example.test","role":"viewer"}`.
Capture actual subject bindings from trusted provider administration; browser
claims, emails alone and provider groups cannot seed trusted links. No passwords,
tokens or extra fields belong in the manifest. Seeding is explicit reconciliation;
conflicting identities fail. Cleanup deletes bounded expired/revoked login state
without renewing sessions. Users remain seeded throughout scope; there is no
registration or Admin user-management feature.

## Controlled local verification

Use a disposable loopback PostgreSQL instance whose test user can create/drop
test databases. The suite rejects non-loopback hosts and does not connect to RDS.
To provision Docker PostgreSQL and install the pinned browser:

```sh
make setup
make test-postgres
# Wait for readiness:
docker exec outage-explorer-test-postgres pg_isready -U outage_test -d postgres
export OUTAGE_TEST_POSTGRES_DSN='host=127.0.0.1 port=55439 dbname=postgres user=outage_test password=controlled-test-only sslmode=disable'
make test-browser-setup
make check
# After the tests:
make test-postgres-stop
```

An existing disposable native PostgreSQL instance is also supported with an
explicit test DSN. PostgreSQL and Chromium are required for full verification;
missing setup fails rather than silently skipping. CI provisions PostgreSQL 18,
installs Chromium and runs Ruff, mypy, architecture negative fixtures, unit,
HTTP/integration/acceptance/browser tests and distribution build on Python 3.12
and 3.14. Live-provider checks are explicitly opt-in and receive no cloud
credentials in required CI. The browser harness uses controlled server time and
actual persistent profiles, including reopen, cookie flags, logout CSRF,
revocation/expiry and independent sessions. It does not need the separate UI,
connector, S3, EC2 or analytical data.
