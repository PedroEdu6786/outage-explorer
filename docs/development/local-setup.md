# Local application setup

[Back to README](../../README.md)


Keep the `outage-explorer` and `outage-explorer-web` checkouts next to each other.
The web client is implemented in the [separate repository](https://github.com/PedroEdu6786/outage-explorer-web); the backend owns
authentication, authorization, stored observations, SQL execution and refresh.

### Prerequisites and configuration

- Python 3.12+ for the backend; Node 24.18.0 and npm 11.16.0 for the web client.
- AWS CLI with a working local login for the profiles configured below.
- Apple Silicon macOS with Docker CLI and the dedicated Colima `outage-runtime`
  Linux VM, matching the environment used for this project. Follow the single
  environment in the [fresh-machine walkthrough](fresh-machine.md).
- Configured PostgreSQL/RDS, Cognito and S3 resources, three seeded persona
  bindings, and a published three-resource generation for browsing stored data.
- For preview and SQL, matching actual-host analytical/parser configuration and
  containment review. The walkthrough generates these from this machine's tests;
  another machine's reviewed files are insufficient.

### Manual fresh-machine setup

Run `make local-help` for the Make command sequence. Follow the
[numbered fresh-machine walkthrough](fresh-machine.md) from dependency
installation through browser sign-in and recovery. It includes Docker setup,
pinned source installation, dedicated Colima commands, actual-host
containment checks, a checked-in API entry point and private configuration
installation. `make run-analytical` starts the configured service and renews
credentials; preparation and review are explicit earlier steps. `/run` files
must be restored after reboot as documented there.

### Application configuration

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
```

New Admin refreshes use this configured start through today's UTC date, with no
fixed day-count ceiling. The exact range is saved per run; EIA publication can
lag behind today. Finite connector resource budgets still apply. See
[refresh configuration](connector.md#product-refresh-worker) for limits and
obsolete settings to remove. Changing the start requires an API restart.

Register the exact callback above and the sign-out URL
`http://localhost:3000/sign-in` in the Cognito app client. Configure
`COGNITO_ISSUER`, `COGNITO_DOMAIN`, `COGNITO_APP_CLIENT_ID` and explicit
`COGNITO_OAUTH_SCOPES` for that same client. The Linux API uses its own private
runtime configuration: changes to backend `.env` are not automatically installed
there; stop the API and rerun the walkthrough’s configuration step. The launcher reads local AWS profile selection from `.env` and renews
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
# Terminal 1: configured backend on macOS, dedicated Colima outage-runtime VM
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

Run the backend checks using the disposable PostgreSQL/Chromium instructions in the [testing guide](testing.md). In the web checkout, run `npm run typecheck`, `npm run lint`, `npm test`
and `npm run build`; its README documents additional boundary and browser checks.
Reproduce the three findings with the commands linked from [FINDINGS.md](../../FINDINGS.md).

The user confirmed on October 7, 2026 that integrated acceptance is complete,
including the earlier confirmation that SQL denials work as expected. This records
user acceptance; no additional automated or browser validation is claimed here.
Fresh-machine provisioning remains separate from that accepted integration.
EC2 deployment is not required for this local workflow.
