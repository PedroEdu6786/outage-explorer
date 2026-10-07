# Fresh-machine walkthrough

[README](../../README.md) · [Application settings](local-setup.md) ·
[Web repository](https://github.com/PedroEdu6786/outage-explorer-web)

Follow the numbered steps in order. Commands are manual: reading this document
installs nothing. Replace example resource identifiers with values from your
environment owner. Keep credentials out of Git and terminal output.

## Make command checklist

After cloning and installing Homebrew, run from the backend checkout:

```sh
make local-dependencies
# Open a new terminal after the printed Python/nvm shell setup instructions.
make setup
make local-runtime
make local-candidate
make local-validate
make local-reports
make local-review REVIEWER="Your name"
```

Read the reports before the review command. Configure your AWS login and `.env`
using steps 4–5, then run `make local-configure`. Start `make run-analytical`
and `make local-forward` in separate terminals. Start the web client with
`npm run dev` in its checkout after step 10. `make local-help` prints this sequence.
The details below explain prerequisites and what each step does.

## 1. Use the required environment

Use **Apple Silicon macOS with the dedicated Colima `outage-runtime` VM**,
matching the environment used for this project. The checked-in creation helper
selects aarch64, Apple's VZ backend, Docker, 4 CPUs, 6 GiB RAM and 20 GiB disks.
These are initial setup allowances, not measured application capacity.

Python, AWS CLI, the web client and browser run on macOS. The API and analytical
controller run inside this Colima Linux VM; analytical workers run in its Docker
daemon and the SQL parser runs in a bounded Linux subprocess. The Docker CLI
alone is insufficient. Follow the single Colima sequence below throughout.

The VM has no host directory mounts, SSH-agent forwarding or automatic port
forwarding. The guide installs source explicitly and forwards the API port in
a dedicated terminal. You need administrator access and enough disk/memory to
create this VM.

## 2. Obtain the environment settings

Ask the environment owner for this checklist before installation:

- RDS endpoint, region, database, application user and either IAM login access
  or a password connection string; network/VPN access from your Linux host.
- An AWS profile allowed to read the configured S3 bucket/prefix and, for IAM
  database mode, to connect as the configured database user.
- Cognito issuer, hosted domain, app client ID, allowed OAuth scopes and client
  secret if this is a confidential client.
- A seeded Viewer, Analyst or Admin login. All three are needed to check every
  role. There is no default password or public registration.
- An already published generation containing national, facilities and generators
  resources, with its exact descriptors in PostgreSQL.

This walkthrough reuses configured AWS resources. It does not provision an AWS
account, create users, migrate a shared database or publish data. If you own a
new environment, first follow [database/Cognito migration and seeding](../specs/user-access/setup.md),
[S3 and connector setup](connector.md), and the
[refresh specification](../specs/refresh-persistence/spec.md). Run migrations/seeding only
against the intended environment with the appropriate operator credentials.
A connector upload receipt alone does not publish data. EIA credentials are
needed for refresh, not for browsing existing published data.

## 3. Install the dependencies

On Apple Silicon macOS, install [Homebrew](https://brew.sh/) if needed. Clone
both repositories and enter the backend checkout:

```sh
mkdir -p ~/Projects
cd ~/Projects
git clone https://github.com/PedroEdu6786/outage-explorer.git
git clone https://github.com/PedroEdu6786/outage-explorer-web.git
cd outage-explorer
```

Then install the host dependencies:

```sh
make local-dependencies
export PATH="$(brew --prefix python@3.12)/libexec/bin:$PATH"
```

Keep that Python directory on your shell's PATH for future terminals. Colima
provides the Linux VM and Docker daemon; the Docker package provides its host
CLI. See [Colima's installation instructions](https://colima.run/docs/installation/).
The guest's Python/system dependencies are installed by the repository helper
in step 6. Docker Desktop is not part of this setup.

The target also installs AWS CLI and nvm. Follow Homebrew’s printed nvm shell
initialization instructions, then open a new terminal. The web repository’s
pinned Node version is installed in step 10.
Verify `git --version`, `make --version`, `python3 --version`, `aws --version`,
`colima version` and `docker --version`. Python must be 3.12 or later.
The daemon is created in step 6.

## 4. Install backend dependencies and configure AWS login

Run on macOS:

```sh
cd ~/Projects/outage-explorer
make setup
mkdir -p .local-runtime
chmod 700 .local-runtime
test -f .env || cp .env.example .env
chmod 600 .env
```

Use your organization's AWS login method for a named profile. For IAM Identity
Center, [configure SSO](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html)
then sign in:

```sh
aws configure sso --profile outage-explorer
aws sso login --profile outage-explorer
aws sts get-caller-identity --profile outage-explorer
```

Other account types need their owner's login procedure. The launcher uses
`aws configure export-credentials` privately and renews credentials every minute;
do not run that command to print secrets. The identity check above is read-only.

## 5. Fill in backend settings

Download the RDS CA bundle to this checkout:

```sh
curl --fail --location https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem --output .local-runtime/rds-ca.pem
```

Edit `.env`, preserving secrets privately. For IAM mode, **remove the entire
`OUTAGE_ACCESS_DATABASE_DSN=` line**, even if empty. Set these values with your
actual identifiers; use an absolute CA path, not the placeholder below:

```dotenv
AWS_PROFILE=outage-explorer
AWS_REGION=us-east-1
OUTAGE_S3_BUCKET=YOUR_BUCKET
OUTAGE_S3_PREFIX=data/
OUTAGE_ACCESS_DATABASE_MODE=iam
OUTAGE_ACCESS_DATABASE_HOST=YOUR_ACTUAL_ENDPOINT.rds.amazonaws.com
OUTAGE_ACCESS_DATABASE_PORT=5432
OUTAGE_ACCESS_DATABASE_NAME=YOUR_DATABASE
OUTAGE_ACCESS_DATABASE_USER=YOUR_IAM_DATABASE_USER
OUTAGE_ACCESS_DATABASE_REGION=us-east-1
OUTAGE_ACCESS_DATABASE_PROFILE=outage-explorer
OUTAGE_ACCESS_DATABASE_SSLROOTCERT=/ABSOLUTE/PATH/outage-explorer/.local-runtime/rds-ca.pem
COGNITO_ISSUER=https://cognito-idp.us-east-1.amazonaws.com/YOUR_POOL_ID
COGNITO_DOMAIN=https://YOUR_DOMAIN.auth.us-east-1.amazoncognito.com
COGNITO_APP_CLIENT_ID=YOUR_CLIENT_ID
COGNITO_OAUTH_SCOPES=YOUR_CLIENT_ALLOWED_SCOPES
OUTAGE_AUTH_ENABLED=true
OUTAGE_DATA_HTTP_ENABLED=true
OUTAGE_AUTH_PUBLIC_ORIGIN=http://localhost:8000
OUTAGE_AUTH_CALLBACK_URI=http://localhost:8000/api/auth/callback
OUTAGE_AUTH_UI_ORIGIN=http://localhost:3000
OUTAGE_AUTH_RETURN_PATHS=/,/overview,/datasets,/query
OUTAGE_AUTH_DEVELOPMENT_HTTP=true
OUTAGE_REFRESH_START_DATE=2026-04-02
```

Supply `COGNITO_APP_CLIENT_SECRET` privately if required. Scopes must match the
client; use its owner's values. Register the exact callback above and
`http://localhost:3000/sign-in` as the Cognito sign-out URL.

For password authentication, use `OUTAGE_ACCESS_DATABASE_MODE=password` and a
single `OUTAGE_ACCESS_DATABASE_DSN` containing `host`, `port`, `dbname`, `user`,
`password`, `sslmode=verify-full` and `sslrootcert=/absolute/path/to/rds-ca.pem`.
Remove every other `OUTAGE_ACCESS_DATABASE_*` assignment. Follow the
[database mode rules](../specs/user-access/setup.md); `PG*` alone does not configure
the application. The configuration helper copies the CA to Linux and rewrites
its path. Keep RDS network access limited to the intended developer host/VPN.

## 6. Prepare the runtime with Make

Run these from the macOS backend checkout, one at a time:

```sh
make local-help
make local-runtime
make local-candidate
```

`local-runtime` checks that the source to export is committed, creates the
required Colima VM, prepares its Linux dependencies/private spill storage,
transfers committed source and installs pinned dependencies/builds the worker
image. It excludes `.env`, credentials and Git history. It is a **fresh-install**
command: existing resources are preserved and cause preparation to refuse.
Do not use it to repair an existing installation.

`local-candidate` captures this guest's daemon, image, filesystem and parser
executable identities. It refuses existing candidate files. No API or refresh
worker starts. Logs stay in `/var/lib/outage-runtime-validation/` inside Colima.

## 7. Check and review containment

```sh
make local-validate
make local-reports
```

The first command runs controlled tests, native parser checks and actual Docker
containment/lifecycle tests inside Colima as UID/GID 65534, with the actual
Docker socket group. The second prints the XML and JSON evidence for inspection.
All selected tests and required gates must pass without skips. Investigate
failures; do not copy another machine's review or edit reports to pass startup.

After personally reviewing the successful reports, record your explicit review:

```sh
make local-review REVIEWER="Your name"
```

This binds the passing reports to the exact profiles, runs the exact parser smoke
check and records a private named review. It accepts **local preview/SQL with
refresh idle**. Capacity/high-water/spill measurements, S3 performance and
API/refresh overlap remain deferred. External services are not verified by this
command. Existing reviews are preserved; review does not start the application.

## 8. Install private API settings

Complete AWS login and `.env` from steps 4–5, then run:

```sh
make local-configure
```

This copies the guest's reviewed settings and installs the checked-in entry point,
private configuration and RDS CA under `/run/outage-api`. It reads `.env` plus
exported overrides, refuses configuration while the API is running and does not
start services or export AWS credentials. EIA credentials remain excluded:
refresh has its own configuration and process.

## 9. Start the API

In a dedicated macOS backend terminal:

```sh
make run-analytical
```

`make run` is the separate macOS Flask health/docs scaffold; it does not provide
preview/SQL execution. Use `make run-analytical` for this complete application.

Keep this process running for credential renewal. It starts one threaded API
process and preserves one analytical execution slot. Credentials go only to
the trusted API, not to analytical containers.

Use a second macOS terminal for explicit port forwarding:

```sh
make local-forward
```

Keep this terminal running too. The macOS web client and browser reach the
guest API through this localhost forwarding.

Check from the machine running the browser:

```sh
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/api/openapi.json
```

These check reachability and documentation, not login or analytical acceptance.

## 10. Configure and start the web client

In another macOS terminal:

```sh
cd ~/Projects/outage-explorer-web
nvm install
nvm use
npm install --global npm@11.16.0
npm ci
test -f .env.local || cp .env.example .env.local
chmod 600 .env.local
```

The repository's `.nvmrc` selects Node 24.18.0. Set these in `.env.local`:

```dotenv
OUTAGE_API_ORIGIN=http://localhost:8000
OUTAGE_AUTH_LOGOUT_URI=http://localhost:3000/sign-in
COGNITO_DOMAIN=https://YOUR_DOMAIN.auth.us-east-1.amazoncognito.com
COGNITO_APP_CLIENT_ID=YOUR_CLIENT_ID
```

Copy only the same public domain and client ID from the backend; keep secrets
and AWS/database credentials on the backend. Start Next.js:

```sh
npm run dev
```

Open **http://localhost:3000**. Use `localhost` consistently for both applications.
Sign in with a seeded account. Viewer sees national data; Analyst sees all
datasets, previews and SQL; Admin adds refresh admission/outcomes. Browse a
published dataset or run an allowed query as Analyst. A missing generation needs
owner-directed publication, not a database reset. API documentation is at
`http://localhost:8000/api/docs`.

Refresh remains idle throughout this walkthrough. To process an explicitly
requested refresh, configure and supervise `make run-worker` independently using
[the refresh worker instructions](connector.md#product-refresh-worker).

## 11. Stop, restart and troubleshoot

Ctrl+C in the API supervisor stops the API; Ctrl+C also stops the web server
and SSH forwarding in their respective terminals. From another backend terminal,
use `make stop-analytical` on macOS.
API restarts invalidate process-owned result IDs/cursors; start a new preview or
explicitly rerun the SQL afterward. Restart Next.js after editing its settings.

| Symptom | Next check |
| --- | --- |
| Docker connection denied | The `outage-runtime` Colima guest is running; its Docker socket group matches the controller. |
| Setup refuses an existing path | Preserve existing evidence; this is a fresh-install helper. Use the existing installation's recovery procedure. |
| Configuration fails | Reviewed identities match; API is stopped; CA file exists; `.env` uses one valid database mode. |
| API fails to start | AWS login/profile is current; Linux service configuration is installed; inspect `colima ssh --profile outage-runtime -- sudo journalctl -u outage-api-local` privately. |
| Browser cannot reach API on macOS | SSH forwarding is running and port 8000 is free. |
| Cognito redirect fails | Client callback, sign-out URL, scopes and both localhost origins match exactly. |
| Preview/SQL unavailable | Check actual containment tests, matching reviewed profiles and published generation descriptors. |
| RDS connection fails | Endpoint/region/user, verified CA, IAM grants or password, and host network/VPN access. |

After a guest reboot, `/run/outage-api` is gone. Enter the guest with
`colima ssh --profile outage-runtime --` and restore the spill mount before startup
if `mountpoint /var/lib/outage-analytical/spill` reports it is not mounted:

```sh
sudo mount -o loop,rw,noexec,nosuid,nodev /var/lib/outage-analytical/spill.img /var/lib/outage-analytical/spill
```

Exit the guest shell, then repeat step 8 from macOS and start the API. If filesystem, daemon, image or parser
identities changed, preserve the previous candidate/reports/review as an archive
outside the active report directory and repeat steps 7–8 for the new identities.
Do not patch old evidence. Source updates require installing the new committed
revision and rebuilding the image before collecting new evidence. Fresh
preparation is not an update command. See the
[runtime recovery contract](../../infrastructure/analytical-worker/README.md).

The guide and setup helpers have controlled automated coverage. A complete
fresh Colima installation has not been executed for this documentation
change; the actual-host tests in step 7 are mandatory evidence for your host.
Existing integrated acceptance was confirmed by the user on October 7, 2026.
