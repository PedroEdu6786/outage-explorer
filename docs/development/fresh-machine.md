# Fresh-machine walkthrough

[README](../../README.md) · [Application settings](local-setup.md) ·
[Web repository](https://github.com/PedroEdu6786/outage-explorer-web)

Follow the numbered steps in order. Commands are manual: reading this document
installs nothing. Replace example resource identifiers with values from your
environment owner. Keep credentials out of Git and terminal output.

## 1. Choose where Linux will run

The API and analytical controller run on the **Linux Docker daemon host**.
The analytical worker runs in Docker; the SQL parser runs in a bounded Linux
subprocess. Docker CLI alone is insufficient.

| Your computer | Recommended route |
| --- | --- |
| Ubuntu 24.04 | Run everything on this machine, using the native commands below. |
| Windows or macOS | Use an Ubuntu 24.04 VM and follow the native commands inside it. Open the browser inside the VM too. |
| Apple Silicon macOS | Alternatively, use the dedicated Colima route below; Python, AWS CLI, web client and browser stay on macOS. |

For an Ubuntu VM, use a hypervisor supporting your CPU architecture and an
[Ubuntu installer](https://ubuntu.com/download/desktop). Start with 4 CPUs,
6 GiB RAM and at least 20 GiB disk. These are setup allowances, not measured
application capacity. The runtime needs systemd, cgroups, loop mounts and ext4;
a direct macOS/Windows API process or a remote Docker socket does not supply it.
Use a dedicated development machine/VM: the preparation step creates private
system directories and a deliberately small, bounded spill filesystem.

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

On Ubuntu 24.04 (native machine or VM):

```sh
sudo apt-get update
sudo apt-get install -y git make curl ca-certificates python3 python3-venv python3-pip util-linux e2fsprogs
python3 --version
```

Python must be 3.12 or later. Install **Docker Engine**, including its CLI,
using Docker's [Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/).
Use the official apt repository instructions for your architecture. Then enable
the daemon and allow your development account to run the CLI:

```sh
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Log out and back in before continuing so the new group takes effect. Docker
group membership grants control of the local daemon; use it only on the trusted
development host. Check both CLI and daemon:

```sh
docker --version
docker info --format '{{.ServerVersion}} {{.OSType}} {{.Architecture}}'
systemctl is-system-running
```

The daemon must report Linux. Investigate failed system services if systemd
reports `degraded`; do not proceed with a broken Docker service.

On Apple Silicon using Colima, install Git, Make and Python 3.12+ on macOS,
then install the [Colima dependencies](https://colima.run/docs/installation/):

```sh
brew install colima docker
```

For either route, install **AWS CLI v2** using the
[official instructions for your host](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).
Install [nvm](https://github.com/nvm-sh/nvm#install--update-script) on the host
that will run the web client; its pinned Node version is installed in step 10.
Verify `git --version`, `make --version`, `python3 --version` and `aws --version`.

## 4. Clone both repositories and configure AWS login

Run on Ubuntu for the native route, or on macOS for Colima:

```sh
mkdir -p ~/Projects
cd ~/Projects
git clone https://github.com/PedroEdu6786/outage-explorer.git
git clone https://github.com/PedroEdu6786/outage-explorer-web.git
cd outage-explorer
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

## 6. Prepare the Linux runtime and install this revision

**Native Ubuntu:** run from the backend checkout:

```sh
sh infrastructure/analytical-worker/native-linux-validation/prepare-guest.sh
```

**Colima:** run these instead, from the macOS backend checkout:

```sh
sh infrastructure/analytical-worker/native-linux-validation/start-colima.sh
colima ssh --profile outage-runtime -- sh -s < infrastructure/analytical-worker/native-linux-validation/prepare-guest.sh
```

The Colima helper creates a separate `outage-runtime` VM without host mounts,
agent forwarding or automatic port forwarding. The preparation script refuses
existing runtime resources. Do not rerun it to repair an existing installation.

Archive committed source only. These commands deliberately omit `.env`, AWS
credentials and Git history. A successful diff check prints nothing; if it fails,
commit or otherwise resolve your intended source changes before continuing:

```sh
git diff --quiet HEAD -- src tests scripts infrastructure/analytical-worker pyproject.toml requirements-dev.txt README.md
git archive --format=tar --output=.local-runtime/source.tar HEAD src tests scripts infrastructure/analytical-worker pyproject.toml requirements-dev.txt README.md
```

Native Ubuntu:

```sh
sudo tar -xf .local-runtime/source.tar -C /opt/outage-runtime-validation
sh infrastructure/analytical-worker/native-linux-validation/build-guest.sh
```

Colima, instead:

```sh
colima ssh --profile outage-runtime -- sudo tar -xf - -C /opt/outage-runtime-validation < .local-runtime/source.tar
colima ssh --profile outage-runtime -- sh /opt/outage-runtime-validation/infrastructure/analytical-worker/native-linux-validation/build-guest.sh
```

This installs the pinned Python dependencies and package, then builds the
analytical Docker image. Success prints its image identity/platform and engine
versions. Logs stay in `/var/lib/outage-runtime-validation/` on Linux. No API,
refresh worker, AWS migration or publication starts here.

## 7. Generate and check this machine's containment evidence

For Colima, first enter Linux with `colima ssh --profile outage-runtime --`.
For native Ubuntu, stay in your existing terminal. On **Linux**, enter the
unprivileged controller shell with the actual socket group:

```sh
cd /opt/outage-runtime-validation
outage_docker_group=$(stat -c %g /run/docker.sock)
sudo setpriv --reuid=65534 --regid=65534 --groups="$outage_docker_group" env -i PATH=/usr/bin:/bin HOME=/nonexistent PYTHONDONTWRITEBYTECODE=1 /bin/bash --noprofile --norc
```

Run the following inside that shell. Candidate generation discovers the daemon,
image, filesystem and parser executable identities; it refuses existing outputs.

```sh
.venv/bin/python infrastructure/analytical-worker/native-linux-validation/create-profile.py
.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit tests/architecture tests/test_local_analytical.py tests/test_local_runtime_setup.py tests/integration/test_sql_compatibility.py --junitxml=/var/lib/outage-runtime-validation/controlled.xml
.venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/test_sql_parser_process.py --junitxml=/var/lib/outage-runtime-validation/parser.xml
OUTAGE_RUNTIME_TEST_PROFILE=/var/lib/outage-runtime-validation/candidate.json OUTAGE_RUNTIME_DOCKER_EXECUTABLE=/usr/bin/docker .venv/bin/python -m pytest -q -p no:cacheprovider tests/acceptance/test_query_runtime.py -m runtime_docker --junitxml=/var/lib/outage-runtime-validation/docker.xml
```

These are local tests using synthetic inputs. Docker tests exercise isolation,
resource limits, termination, restart and cleanup. Failures must be investigated;
do not copy another machine's review or edit a report to make startup pass.
Inspect the XML summaries and the JSON reports:

```sh
ls /var/lib/outage-runtime-validation/owned/validation-reports
cat /var/lib/outage-runtime-validation/controlled.xml
cat /var/lib/outage-runtime-validation/parser.xml
cat /var/lib/outage-runtime-validation/docker.xml
cat /var/lib/outage-runtime-validation/owned/validation-reports/*.json
```

All selected tests and required containment gates must pass without skips,
including the bounded CPU throttling probe. Full representative capacity
measurements are a separate deferred checkpoint.

After personally reviewing successful reports, explicitly record your local
review, substituting your name:

```sh
.venv/bin/python scripts/review_local_runtime.py --reviewer "YOUR NAME" --accept-local-containment
exit
```

This command checks report/profile matches and runs an additional smoke check
with the exact parser configuration. It writes `local-scope-review.json`,
`runtime-reviewed.json` and `parser-reviewed.json`, with private permissions.
It accepts only the scoped local preview/SQL path with **refresh idle**. It does
not measure production budgets, high-water/spill capacity, S3 performance or
API/refresh overlap, and does not validate your external resources or start the
API. Full runtime acceptance remains separate. Numeric defaults are initial
limits. Existing review files are preserved rather than overwritten.

For Colima, also `exit` the guest SSH shell to return to macOS.

## 8. Install private API configuration

Back in your backend checkout, copy the nonsecret reviewed settings.
Native Ubuntu:

```sh
sudo cat /var/lib/outage-runtime-validation/runtime-reviewed.json > .local-runtime/runtime-reviewed.json
sudo cat /var/lib/outage-runtime-validation/parser-reviewed.json > .local-runtime/parser-reviewed.json
sudo -v
.venv/bin/python scripts/local_analytical.py --native --configure --config .local-runtime/runtime-reviewed.json --inspection-config .local-runtime/parser-reviewed.json
```

Colima, instead:

```sh
colima ssh --profile outage-runtime -- sudo cat /var/lib/outage-runtime-validation/runtime-reviewed.json > .local-runtime/runtime-reviewed.json
colima ssh --profile outage-runtime -- sudo cat /var/lib/outage-runtime-validation/parser-reviewed.json > .local-runtime/parser-reviewed.json
.venv/bin/python scripts/local_analytical.py --configure --config .local-runtime/runtime-reviewed.json --inspection-config .local-runtime/parser-reviewed.json
```

Then `chmod 600 .local-runtime/*reviewed.json`. Configuration reads backend
`.env` plus exported environment overrides, installs the checked-in entry point,
reviewed files and private settings under `/run/outage-api`, and copies the RDS
CA. It refuses reconfiguration while the API is running. It does not export AWS
credentials or start services. It intentionally excludes EIA credentials:
refresh has its own process and configuration.

## 9. Start the API

Native Ubuntu, in a dedicated backend terminal:

```sh
sudo -v
make run-analytical NATIVE=1
```

Colima, instead:

```sh
make run-analytical
```

Keep this process running for credential renewal. It starts one threaded API
process and preserves one analytical execution slot. Credentials go only to
the trusted API, not to analytical containers.

For Colima, use a second macOS terminal for explicit port forwarding:

```sh
cd ~/Projects/outage-explorer
colima ssh-config --profile outage-runtime > .local-runtime/ssh-config
chmod 600 .local-runtime/ssh-config
ssh -F .local-runtime/ssh-config -o ExitOnForwardFailure=yes -N -L 127.0.0.1:8000:127.0.0.1:8000 colima-outage-runtime
```

Keep this terminal running too. For Ubuntu VMs, the simple route is to run the
web client and browser inside Ubuntu; `localhost` then reaches the same API.

Check from the machine running the browser:

```sh
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/api/openapi.json
```

These check reachability and documentation, not login or analytical acceptance.

## 10. Configure and start the web client

In another terminal on Ubuntu (native/VM) or macOS (Colima):

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
use `make stop-analytical NATIVE=1` on Ubuntu or `make stop-analytical` for Colima.
API restarts invalidate process-owned result IDs/cursors; start a new preview or
explicitly rerun the SQL afterward. Restart Next.js after editing its settings.

| Symptom | Next check |
| --- | --- |
| Docker connection denied | Daemon is running; logged-in user has the new Docker group. |
| Setup refuses an existing path | Preserve existing evidence; this is a fresh-install helper. Use the existing installation's recovery procedure. |
| Configuration fails | Reviewed identities match; API is stopped; CA file exists; `.env` uses one valid database mode. |
| API fails to start | AWS login/profile is current; Linux service configuration is installed; inspect `sudo journalctl -u outage-api-local` privately. |
| Browser cannot reach API on macOS | SSH forwarding is running and port 8000 is free. |
| Cognito redirect fails | Client callback, sign-out URL, scopes and both localhost origins match exactly. |
| Preview/SQL unavailable | Check actual containment tests, matching reviewed profiles and published generation descriptors. |
| RDS connection fails | Endpoint/region/user, verified CA, IAM grants or password, and host network/VPN access. |

After reboot, `/run/outage-api` is gone. Restore the spill mount before startup
if `mountpoint /var/lib/outage-analytical/spill` reports it is not mounted:

```sh
sudo mount -o loop,rw,noexec,nosuid,nodev /var/lib/outage-analytical/spill.img /var/lib/outage-analytical/spill
```

Then repeat step 8 and start the API. If filesystem, daemon, image or parser
identities changed, preserve the previous candidate/reports/review as an archive
outside the active report directory and repeat steps 7–8 for the new identities.
Do not patch old evidence. Source updates require installing the new committed
revision and rebuilding the image before collecting new evidence. Fresh
preparation is not an update command. See the
[runtime recovery contract](../../infrastructure/analytical-worker/README.md).

The guide and setup helpers have controlled automated coverage. A complete
fresh Ubuntu/Colima installation has not been executed for this documentation
change; the actual-host tests in step 7 are mandatory evidence for your host.
Existing integrated acceptance was confirmed by the user on October 7, 2026.
