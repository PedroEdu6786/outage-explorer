# Local application setup

[Back to README](../../README.md)


Keep the `outage-explorer` and `outage-explorer-web` checkouts next to each other.
The web client is implemented in the [separate repository](https://github.com/PedroEdu6786/outage-explorer-web); the backend owns
authentication, authorization, stored observations, SQL execution and refresh.

### Prerequisites and configuration

- Python 3.12+ for the backend; Node 24.18.0 and npm 11.16.0 for the web client.
- AWS CLI with a working local login for the profiles configured below.
- Docker CLI and a Linux Docker daemon. The existing local launcher uses Colima's
  dedicated `outage-runtime` guest; installing the Docker CLI alone is insufficient.
  The supplied VM creation helper targets Apple Silicon macOS with Colima's VZ
  backend. Other hosts need their own runtime setup; these helpers do not establish
  a portable Docker Desktop or native Linux application startup path.
- Configured PostgreSQL/RDS, Cognito and S3 resources, three seeded persona
  bindings, and a published three-resource generation for browsing stored data.
- For preview and SQL, the already provisioned and reviewed `outage-runtime`
  Colima Linux environment, analytical image, private runtime configuration and
  local port forwarding. `make run-analytical` uses this environment; it does
  not create it. A fresh machine needs this operator setup before full application
  startup; installing Python dependencies alone is insufficient. See the
  [analytical runtime contract](../../infrastructure/analytical-worker/README.md) and
  [local startup evidence](../../docs/specs/data-api/runtime-evidence.md).

### Manual fresh-machine setup

**Partial setup is available.** The repository contains manual helpers to create
the dedicated Colima VM, prepare the Linux filesystem and Python environment,
build the Docker worker image, and generate a candidate runtime profile:

1. Install Git, Python, Node/npm, AWS CLI, Docker CLI and Colima on the host.
   Clone this backend and the linked web repository into sibling directories.
2. Follow the [dedicated Colima setup sequence](../../infrastructure/analytical-worker/README.md#recorded-dedicated-colima-validation-october-5-2026).
   Its `start-colima.sh`, `prepare-guest.sh` and `build-guest.sh` helpers create the
   Docker runtime, private spill storage, guest dependencies and worker image.
   Fresh-provisioning helpers refuse existing resources; use their documented
   recovery instructions for an existing guest.
3. Follow the runtime-profile and containment instructions in that runbook.
   New host/image/profile identities need matching review evidence; copying another
   machine's reviewed configuration does not establish readiness on this one.
4. Configure the database, Cognito, S3, seeded users and published data using the
   linked operator guides, then complete the application configuration below.

The remaining manual operator step is **full API guest setup**: install the exact
backend revision, create the private runtime configuration and API entry point
at `/run/outage-api/start.py`, provide its directories/permissions and configure
local port forwarding. The existing launcher also assumes a configured guest
Python at `/opt/outage-runtime-validation/.venv/bin/python` and Docker socket
supplementary group `991`; verify the actual guest group before configuring it.
These steps are not yet supplied as a complete versioned bootstrap procedure.
`/run` is transient, so its application files also need restoration after a guest
reboot. `make run-analytical` renews credentials and starts the configured service;
it does not fill in this missing setup.

Thus we can manually provision the **worker environment including Docker** from
the runbook, but cannot yet claim a complete fresh-machine application setup
using only the delivered instructions. No installation or provisioning runs when
reading this guide.

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

Run the backend checks using the disposable PostgreSQL/Chromium instructions in the [testing guide](testing.md). In the web checkout, run `npm run typecheck`, `npm run lint`, `npm test`
and `npm run build`; its README documents additional boundary and browser checks.
Reproduce the three findings with the commands linked from [FINDINGS.md](../../FINDINGS.md).

The user confirmed on October 7, 2026 that integrated acceptance is complete,
including the earlier confirmation that SQL denials work as expected. This records
user acceptance; no additional automated or browser validation is claimed here.
Fresh-machine provisioning remains separate from that accepted integration.
EC2 deployment is not required for this local workflow.
