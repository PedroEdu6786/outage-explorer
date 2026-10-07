# Local Make commands

[Fresh-machine walkthrough](fresh-machine.md) · [README](../../README.md)

Run these commands from the backend checkout on **Apple Silicon macOS**.
They use the dedicated Colima `outage-runtime` Linux VM. Run setup stages one
at a time, in order; a later command does not automatically run earlier stages.
Stop on a failure and resolve it before continuing.

## At a glance

| Command | What it does |
| --- | --- |
| `make local-help` | Prints the setup sequence. |
| `make local-dependencies` | Installs development tools on macOS through Homebrew. |
| `make setup` | Installs backend dependencies and prepares private local settings. |
| `make local-ca` | Downloads public RDS CA certificates for database TLS verification. |
| `make local-runtime` | Creates/prepares the Colima VM, installs committed source and builds the query-worker image. |
| `make local-candidate` | Records the installed worker/parser and Linux runtime identities. |
| `make local-validate` | Runs tests inside the VM and saves containment evidence. |
| `make local-reports` | Prints the saved test and containment reports for you to read. |
| `make local-review REVIEWER="Your name"` | Records your explicit acceptance of passing local containment evidence. |
| `make local-configure` | Installs private backend settings and reviewed profiles in the VM. |
| `make run-analytical` | Starts the complete API in the VM and renews AWS credentials. |
| `make local-forward` | Makes the VM's API reachable at `http://localhost:8000` on macOS. |
| `make stop-analytical` | Stops the API in the VM. |

## `make local-help`

**Before:** Have Make installed and enter the backend checkout.

**Does:** Prints the ordered setup commands and reminders about configuration.
It installs nothing and starts nothing.

## `make local-dependencies`

**Before:** Have Homebrew, Make and a working `python3` available on Apple Silicon
macOS. The command needs network access to download packages.

**Does:** Runs Homebrew installation for Git, Make, Python 3.12, Colima, Docker
CLI, AWS CLI and nvm. These tools are installed on your Mac. Colima supplies the
Linux Docker daemon later; the host Docker package supplies the CLI.

**After:** Follow Homebrew’s nvm shell initialization instructions. Make selects
the installed Python automatically; no Python PATH export is needed. This command does not
install the web project's Node version, configure AWS login or create the VM.
It delegates repeat installation behavior to Homebrew.

## `make setup`

**Before:** Install host dependencies. Make prefers the available `python3.12`
executable, otherwise `python3`; the selected interpreter must be 3.12+.
An explicit `PYTHON=...` override remains available.

**Does:** Creates the host `.venv` if missing, installs `requirements-dev.txt`,
installs the backend as an editable package and checks dependency compatibility.
It also creates `.local-runtime` with mode 0700 and copies `.env.example` to a
mode-0600 `.env` only if it is missing. Existing `.env` contents are preserved.
Rerunning it updates dependencies and restores private local-file permissions.

**After:** Host backend/operator commands can use `.venv/bin/python`.
This installs dependencies on macOS; VM dependency installation is separate.
It does not start the API or connect to application services.

## `make local-ca`

**Before:** Install host tools. No AWS login is required. This command is optional
if your existing database settings already reference a valid CA file; the
`.local-runtime/rds-ca.pem` filename is not a required application convention.

**Does:** Downloads Amazon RDS’s public global CA bundle over HTTPS into
`.local-runtime/rds-ca.pem`. It checks that the download contains a certificate
before replacing the previous bundle; failed downloads preserve the old file.

**After:** Prints the absolute path to use in the database CA setting. This lets
`sslmode=verify-full` verify the RDS server’s certificate and hostname. It is
public trust material, not a password, IAM token or AWS login. You obtain the
certificates from AWS; generating a self-signed certificate would not establish
trust in the RDS server. See [obtaining and configuring the CA file](fresh-machine.md#obtain-the-rds-ca-file).
Skip this command
if your environment owner already supplied the correct CA file. It starts no
services. Rerunning it downloads the current bundle again.

## `make local-runtime`

**Before:** Install host tools. Commit the source revision you intend to install;
tracked changes in the exported paths cause this command to stop before touching
the VM. Use this command for a fresh runtime installation.

**Does, in order:**

1. Archives selected committed source/build/test files into `.local-runtime/source.tar`.
2. Starts the dedicated aarch64 Colima VM using Apple's VZ backend, 4 CPUs,
   6 GiB RAM, and 20 GiB data/root disk settings.
3. Installs Linux Python/system dependencies and creates private runtime directories
   and a fixed-capacity ext4 spill filesystem.
4. Transfers the source to `/opt/outage-runtime-validation` inside the VM.
5. Installs pinned guest Python dependencies and builds
   `outage-analytical-worker:validation` in the guest Docker daemon.

**After:** The VM and Docker daemon remain running. Guest dependency/build logs
are under `/var/lib/outage-runtime-validation`. The API and refresh worker are
not started. `.env`, AWS credentials and Git history are excluded from the source
archive. VM sizes are initial settings, not measured application budgets.

**Repeat behavior:** Preparation refuses existing spill/source resources. This
is not an update or repair command, and a failed partial installation is not
rolled back automatically. Preserve the existing resources and investigate the
failed step before retrying; see [recovery](fresh-machine.md#11-stop-restart-and-troubleshoot).

## `make local-candidate`

**Before:** Finish `make local-runtime`; the Colima guest must be running.

**Does:** Runs candidate generation inside the VM as controller UID/GID 65534,
with the actual Docker socket group. Captures Docker image/platform/version,
filesystem identities, and parser executable hashes/settings.

**After:** Creates `candidate.json` and `parser-candidate.json` under
`/var/lib/outage-runtime-validation`. These contain no approval evidence yet and
cannot enable the API. Existing candidate files are not overwritten.

## `make local-validate`

**Before:** Generate this runtime's candidates; keep the runtime dedicated to
these checks, with no API or refresh worker running.

**Does:** Runs three test stages inside the VM as the unprivileged controller:
controlled/unit/architecture/SQL compatibility checks, Linux parser subprocess
checks, then real Docker isolation/resource/lifecycle checks. The Docker tests
create and clean up synthetic test containers and inputs. The sequence stops if
a stage fails.

**After:** Writes `controlled.xml`, `parser.xml` and `docker.xml` under
`/var/lib/outage-runtime-validation`, plus JSON files under
`owned/validation-reports`. A failed run may leave partial reports: do not treat
those as successful evidence. Repeated runs replace XML files and add JSON
reports; old failed reports are not silently discarded.

This command does not approve reports, measure full production capacity,
validate AWS resources or start the application.

## `make local-reports`

**Before:** Run validation. Missing report files cause the command to fail.

**Does:** Prints the three XML test reports and saved JSON containment reports
from the guest. It does not rerun tests or change their results.

**After:** Inspect failures, skips, profile matches and cleanup outcomes. All
selected tests and required containment gates must pass before review.

## `make local-review REVIEWER="Your name"`

**Before:** Personally inspect the reports. Supply your actual reviewer name;
this is an explicit acceptance command, not another test-only command.

**Does:** Rejects missing/failed/skipped evidence or mismatched profiles, checks
required containment gates, runs a smoke check with the exact parser profile,
and binds the reports/source identities to your name and review date.

**After:** Writes private `local-scope-review.json`, `runtime-reviewed.json` and
`parser-reviewed.json` under `/var/lib/outage-runtime-validation`. Existing review
outputs are preserved rather than overwritten.

Acceptance covers **local preview/SQL with refresh idle**. Full capacity,
high-water/spill measurements, S3 performance and API/refresh overlap remain
deferred. Review does not start the API or approve production deployment.

## `make local-configure`

**Before:** Run `make setup` and complete the guest review. Fill in backend `.env`
with the intended RDS, Cognito and S3 settings and a readable RDS CA path.
The API must be stopped.

**Does:** Copies reviewed profiles to private files in host `.local-runtime`,
then installs the checked-in API entry point, reviewed profiles, filtered backend
settings and CA bundle under `/run/outage-api` in the VM. Exported environment
variables override `.env`. Settings travel through stdin into private files.

**After:** The API is configured but stopped. This does not log in to AWS, export
credentials, migrate/seed the database or publish data. Repeat after changing
backend settings, or after a guest reboot once the spill mount is restored:
`/run` files are transient. Configuration refuses an active API.

## `make run-analytical`

**Before:** Complete configuration and AWS login for the configured profiles.

**Does:** Exports the current AWS credentials privately, installs a guest credential
provider and starts/restarts the configured API service in Colima. The API uses
one threaded serving process, one analytical execution slot, a bounded parser
subprocess and isolated Docker query workers. Normal startup readiness checks
remain enforced. The host supervisor renews credentials every minute.

**After:** Keep this terminal running. Ctrl+C stops the API. It does not start
the independently supervised refresh worker. API restarts invalidate ephemeral
preview cursors and SQL result IDs.

By comparison, **`make run`** starts the macOS Flask health/docs scaffold without
analytical execution resources; preview and SQL return 503. Credential renewal
is only one of the differences. Use `make run-analytical` for the full application.

## `make local-forward`

**Before:** The Colima guest must be running, and host port 8000 must be free.
Start the API separately before expecting HTTP responses.

**Does:** Saves private SSH connection settings to `.local-runtime/ssh-config`
and keeps an SSH tunnel open from macOS `127.0.0.1:8000` to guest
`127.0.0.1:8000`. It fails if it cannot establish the local forwarding listener.

**After:** Keep this in a separate terminal from the API. The web client/browser
can reach `http://localhost:8000`. Ctrl+C closes forwarding; it does not stop the
API or VM. This command does not start the web client.

## `make stop-analytical`

**Does:** Stops the `outage-api-local` service inside Colima. It leaves the VM,
Docker daemon, web server, SSH tunnel and independent refresh worker running.
Stop the web server and forwarding with Ctrl+C in their terminals.
