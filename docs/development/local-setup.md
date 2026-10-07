# Local application setup

[Back to README](../../README.md)


Keep the `outage-explorer` and `outage-explorer-web` checkouts next to each other.
The web client is implemented in the separate repository; the backend owns
authentication, authorization, stored observations, SQL execution and refresh.

### Prerequisites and configuration

- Python 3.12+ for the backend; Node 24.18.0 and npm 11.16.0 for the web client.
- AWS CLI with a working local login for the profiles configured below.
- Configured PostgreSQL/RDS, Cognito and S3 resources, three seeded persona
  bindings, and a published three-resource generation for browsing stored data.
- For preview and SQL, the already provisioned and reviewed `outage-runtime`
  Colima Linux environment, analytical image, private runtime configuration and
  local port forwarding. `make run-analytical` uses this environment; it does
  not create it. A fresh machine needs this operator setup before full application
  startup; installing Python dependencies alone is insufficient. See the
  [analytical runtime contract](../../infrastructure/analytical-worker/README.md) and
  [local startup evidence](../../docs/specs/data-api/runtime-evidence.md).

From the backend checkout, install dependencies and create `.env` only if it
does not already exist:

```sh
cd outage-explorer
make setup
test -f .env || cp .env.example .env
```

Populate `.env` with the intended environment's values. The
[user-access setup runbook](../../docs/specs/user-access/setup.md) documents database
modes, Cognito configuration and explicit migration/seeding commands. Use
`OUTAGE_ACCESS_DATABASE_*` for the application database; legacy `PG*` values
alone do not configure application access. For IAM mode, omit
`OUTAGE_ACCESS_DATABASE_DSN` entirely, including the empty example assignment.
Supply the confidential client's `COGNITO_APP_CLIENT_SECRET` privately when
applicable.

For the localhost browser flow, use these nonsecret settings alongside the
database, Cognito and S3 configuration:

```dotenv
OUTAGE_AUTH_ENABLED=true
OUTAGE_DATA_HTTP_ENABLED=true
OUTAGE_AUTH_PUBLIC_ORIGIN=http://localhost:8000
OUTAGE_AUTH_CALLBACK_URI=http://localhost:8000/api/auth/callback
OUTAGE_AUTH_UI_ORIGIN=http://localhost:3000
OUTAGE_AUTH_RETURN_PATHS=/,/overview,/datasets,/query
OUTAGE_AUTH_DEVELOPMENT_HTTP=true
OUTAGE_REFRESH_START_DATE=2026-04-02
OUTAGE_REFRESH_END_DATE=2026-10-01
```

Register the exact callback above and the sign-out URL
`http://localhost:3000/sign-in` in the Cognito app client. Configure
`COGNITO_ISSUER`, `COGNITO_DOMAIN`, `COGNITO_APP_CLIENT_ID` and explicit
`COGNITO_OAUTH_SCOPES` for that same client. The Colima API uses its own private
runtime configuration: changes to backend `.env` are not automatically installed
there. The launcher reads local AWS profile selection from `.env` and renews
credentials for the configured service.

In the sibling web checkout, install the pinned dependencies and create
`.env.local` only if absent:

```sh
cd ../outage-explorer-web
nvm install
nvm use
npm ci
test -f .env.local || cp .env.example .env.local
```

Set `OUTAGE_API_ORIGIN=http://localhost:8000` and
`OUTAGE_AUTH_LOGOUT_URI=http://localhost:3000/sign-in` in `.env.local`. Copy the
backend's public `COGNITO_DOMAIN` and `COGNITO_APP_CLIENT_ID` values into the
matching frontend settings. Restart Next.js after changing configuration.
The client secret and AWS/database credentials stay on the backend.

### Start and sign in

Run the backend in one terminal and the web client in another:

```sh
# Terminal 1: backend checkout, existing configured Colima environment
make run-analytical

# Terminal 2: web checkout
npm run dev
```

Open `http://localhost:3000`, then sign in with one of the seeded Cognito users.
Use `localhost` consistently for both origins; mixing it with `127.0.0.1`
breaks the configured cookie/origin flow. API documentation is at
`http://localhost:8000/api/docs`.

| Seeded persona | Expected access |
| --- | --- |
| Viewer | National Overview and national data only |
| Analyst | Overview, all analytical datasets, filtered previews and SQL |
| Admin | Analyst capabilities plus refresh admission and outcomes |

Obtain the actual seeded login emails and passwords from the environment owner
through a private channel. There are no repository-default passwords or public
registration. Fresh environments require one Cognito user per persona and the
trusted PostgreSQL identity/role bindings described in the setup runbook.

Keep the backend command running for credential renewal; Ctrl+C stops the API.
`make stop-analytical` also stops it from another backend terminal. Ctrl+C stops
Next.js. An API restart invalidates process-owned preview cursors and SQL result
IDs; start a new preview or explicitly rerun the query afterward.

Admin refresh processing additionally needs an independently supervised
`make run-worker` process with database, EIA and S3 settings. See
[refresh worker setup](connector.md#product-refresh-worker). It is not started
by either application command. Existing published data can be browsed with
refresh idle; a connector candidate or S3 receipt alone is not publication.

### Verification and limitations

Run the backend checks using the disposable PostgreSQL/Chromium instructions in the [README](../../README.md#tests). In the web checkout, run `npm run typecheck`, `npm run lint`, `npm test`
and `npm run build`; its README documents additional boundary and browser checks.
Reproduce the three findings with the commands linked from [FINDINGS.md](../../FINDINGS.md).

The user confirmed on October 7, 2026 that integrated SQL denials work as
expected. This is user acceptance of that behavior; no additional automated or
browser validation is claimed here. Clean-machine analytical provisioning and
the remaining release evidence are separate from these startup instructions.
EC2 deployment is not required for this local workflow.

