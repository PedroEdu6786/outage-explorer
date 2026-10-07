# Daily development

[README](../../README.md) · [First-time setup](fresh-machine.md) ·
[Make command reference](local-commands.md)

**Use this page after completing first-time setup.** If you have just cloned the
repositories or have not prepared/reviewed the Colima runtime, follow the
[fresh-machine walkthrough](fresh-machine.md) from step 1 through step 10.
It is the single installation guide, including backend and web configuration.

## Start an existing installation

This assumes your `outage-runtime` Colima guest is running, its spill filesystem
is mounted, private API configuration is installed and your AWS login is current.
After a guest reboot, first follow [reboot recovery](fresh-machine.md#11-stop-restart-and-troubleshoot).

Run these in separate macOS terminals and leave them running. If an existing
Colima SSH tunnel already exposes the API at `localhost:8000`, reuse it and skip
terminal 2; do not start a second listener on the same port.

| Terminal | Working directory | Command | Purpose |
| --- | --- | --- | --- |
| 1 | `outage-explorer` | `make run-analytical` | Starts the complete API in Colima and renews credentials. |
| 2 | `outage-explorer` | `make local-forward` | Connects macOS port 8000 to the API inside Colima. |
| 3 | `outage-explorer-web` | `npm run dev` | Starts the web client on port 3000. |

Open **http://localhost:3000** and sign in with a seeded account. Use `localhost`
consistently for both applications. Get credentials privately from the environment
owner; there is no public registration or default password.
API documentation is at `http://localhost:8000/api/docs`.

`make run` starts only the separate macOS Flask health/docs scaffold without
analytical execution resources. Use `make run-analytical` for preview and SQL.

## Refresh worker, when needed

Analytical query workers are launched automatically by the API. The **refresh
worker** is a different process: it fetches EIA data, builds/stores candidate
resources and publishes a verified generation for an admitted Admin refresh.
The API and web startup commands do not start it.

When intentionally processing refreshes, configure its dependencies using the
[refresh worker instructions](connector.md#product-refresh-worker), then run
this from the backend checkout in a fourth terminal:

```sh
make run-worker
```

It loads backend `.env`, including database, EIA and S3 settings, and polls for
admitted runs. Without a running refresh worker, admitted refreshes are not
processed; browsing an existing generation and SQL do not require this process.
Ctrl+C stops this worker. API-only restarts leave it running.

Keep refresh idle for the reviewed local preview/SQL workflow. Running refresh
and analytical workloads together has separate capacity evidence requirements
that remain deferred.

## Where configuration lives

| File | Purpose | Where to find the values |
| --- | --- | --- |
| Backend `.env` | AWS profile, RDS connection, Cognito, S3 and local API settings. | [First-time backend configuration](fresh-machine.md#5-fill-in-backend-settings). |
| Web `.env.local` | Backend origin, public Cognito domain/client ID and logout URL. | [First-time web configuration](fresh-machine.md#10-configure-and-start-the-web-client). |
| Backend `.local-runtime/` | Local source archive, copied reviewed profiles, optional CA bundle and SSH settings. | Created by the documented Make commands. |
| Guest `/run/outage-api/` | Private installed API settings, reviewed profiles, CA and renewed credentials. | Written by `make local-configure` and the API supervisor; lost after a guest reboot. |

Edit the host environment files. The guest uses installed settings, so editing
backend `.env` alone does not update the running API. Keep backend secrets out
of the web file. A custom CA file may live elsewhere; the backend configuration
points to it and the configuration command copies it into the guest.

## Change backend settings

Use the [backend settings in the walkthrough](fresh-machine.md#5-fill-in-backend-settings)
for the setting names and database mode rules. Preserve the existing reviewed
runtime when changing only resource identifiers, origins, dates or credentials.

1. Stop the API supervisor with Ctrl+C in terminal 1.
2. Edit backend `.env`. Renew your AWS login if necessary.
3. From the backend checkout, run:

   ```sh
   make local-configure
   make run-analytical
   ```

Keep terminal 2's forwarding running, or restart it with `make local-forward`
if it was closed. The new API process invalidates old preview cursors and SQL
result IDs; start a new preview or explicitly rerun the query.

Do not rerun `make local-runtime`, candidate generation or review for a settings-only
change. Changes to installed source, worker image, parser executables, daemon or
filesystem identity require the matching runtime installation/review procedure;
see [runtime recovery](fresh-machine.md#11-stop-restart-and-troubleshoot).

## Change web settings

Edit `outage-explorer-web/.env.local`, then stop and restart `npm run dev` in
terminal 3. Use the [web settings in the walkthrough](fresh-machine.md#10-configure-and-start-the-web-client).
If Cognito URLs/client settings or browser origins change, coordinate the backend
and Cognito client settings too; the walkthrough gives the exact localhost URLs.

## Stop

Ctrl+C in each terminal stops that terminal's API supervisor, forwarding or web
server. `make stop-analytical` also stops the API from another backend terminal;
stop its supervisor too before configuring/restarting. These commands leave the
Colima VM and Docker daemon running. API restarts lose ephemeral query/cursor IDs.

## Other developer tasks

- **Command details:** [Make command reference](local-commands.md).
- **Tests:** [backend PostgreSQL/Chromium setup and checks](testing.md); the web
  repository README covers its own checks.
- **Role behavior:** Viewer has national data; Analyst adds all datasets/previews/
  SQL; Admin adds refresh admission and outcomes.
- **Refresh:** remains idle in the normal local workflow. For explicitly requested
  processing, follow [independent refresh worker setup](connector.md#product-refresh-worker).
  API shutdown does not stop a healthy independent refresh worker.
- **Database migrations/seeding:** [operator runbook](../specs/user-access/setup.md).
  These are separate operator actions, not part of daily application startup.
- **Recorded findings:** [FINDINGS.md](../../FINDINGS.md).

Integrated acceptance was confirmed by the user on October 7, 2026. That does
not replace a new machine's containment checks. EC2 deployment is not required
for this local workflow.
