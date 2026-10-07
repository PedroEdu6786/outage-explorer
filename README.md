# Outage Explorer

Explore stored U.S. nuclear outage data, filter observations, run read-only SQL
and inspect the daily share of fleet capacity offline.

| Persona | Access |
| --- | --- |
| Viewer | National data only |
| Analyst | All analytical datasets, previews and SQL |
| Admin | Analyst access plus data refresh |

## Run locally

Start with the page that matches your situation:

- **First time on this machine:** follow the [fresh-machine walkthrough](docs/development/fresh-machine.md)
  in order. It includes installation, AWS/backend settings, containment review and web setup.
- **Already set up:** use [daily development](docs/development/local-setup.md) to start,
  stop or change settings.
- **Need to understand a Make command:** use the [command reference](docs/development/local-commands.md).

The required environment is Apple Silicon macOS with the dedicated Colima
`outage-runtime` VM and configured RDS, Cognito, S3 and published data. The
[web client](https://github.com/PedroEdu6786/outage-explorer-web) is a sibling checkout.

For an existing installation, these commands support browsing published data
and running preview/SQL. Keep them running in separate terminals:

```sh
# Backend checkout, terminal 1
make run-analytical

# Backend checkout, terminal 2: skip if an existing tunnel already exposes the API
make local-forward

# Web checkout, terminal 3
npm run dev
```

The API launches isolated analytical query workers automatically; they have no
separate startup command. **To process Admin refreshes**, additionally run the
independent refresh worker from the backend checkout in a fourth terminal:

```sh
make run-worker
```

Configure its database, EIA and S3 settings using the
[refresh worker instructions](docs/development/connector.md#product-refresh-worker)
before starting it. It polls for admitted runs; the API does not launch it.
Keep it stopped for the reviewed local preview/SQL workflow, which uses refresh
idle; simultaneous refresh/query capacity acceptance remains deferred.

Open **http://localhost:3000** and sign in with a seeded account. Use `localhost`
for both applications. Obtain test-user credentials privately from the owner.
Ctrl+C stops each process.

API: http://localhost:8000 · Swagger: http://localhost:8000/api/docs ·
[OpenAPI](http://localhost:8000/api/openapi.json)

For credential-free health and documentation only, run `make setup`, then
`make run`. This startup has no analytical resources; preview/SQL return 503.

## Tests

Run `make check` after the [PostgreSQL and Chromium test setup](docs/development/testing.md).
It checks dependencies, Ruff, mypy, pytest and package builds. The same guide
includes web-client checks. Run `make help` for backend commands.

## Connector and failure behavior

The connector retrieves three EIA routes into verified Parquet. Admin refresh
runs independently; publication succeeds only after all three files are verified.

- **Credentials:** missing keys/configuration fail before source work; EIA
  `401`/`403` responses fail without retrying the rejected request.
- **Network:** transient errors, `429` and `5xx` use bounded backoff/retries;
  exhausted attempts or deadlines fail the run.
- **Bad data:** invalid rows are excluded with reasons and prior valid rows
  retained where applicable. Malformed responses or failed pages fail the run.
- **Storage:** failed S3 persistence preserves the local candidate for explicit
  retry, with no automatic local-only fallback. Failed refreshes preserve published data.

See [connector operations](docs/development/connector.md) for commands, exit
codes, initial-load requirements, all-excluded handling and recovery.

## Architecture

Python/Flask layered monolith · PostgreSQL on RDS for operational state ·
S3 Parquet for durable data · isolated DuckDB workers for SQL · Cognito for identity.
The [web repository](https://github.com/PedroEdu6786/outage-explorer-web) contains
the React, Next.js, TypeScript and Tailwind CSS client and its setup instructions.

See [architecture](docs/context/architecture.md) and the
[schema/ER diagrams](docs/context/data-model.md). The fleet metric is
`100 × national outage MW / national capacity MW`.

## Findings and engineering notes

[Reconciliation](docs/challenge/reconciliation.md) covers a 30-day baseline plus
historical samples: **182 sampled dates and 11,182 facility/day groups**.
It includes seven analytical discussion points and offline reproduction commands.

- [FINDINGS.md](FINDINGS.md): reconciliation and three real anomalies.
- [DECISIONS.md](DECISIONS.md): choices, alternatives and rationale.
- [NOTES.md](NOTES.md): my contributions, AI use, corrections and verification.
- [Challenge index](docs/challenge/README.md): requirements and supporting evidence.

Current scope uses seeded users, one backend replica and one analytical slot.
Clean-machine analytical provisioning and EC2 deployment remain separate work.
