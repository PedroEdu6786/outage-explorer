# Architecture

Status: **layered Python/Flask monolith implemented; deployment and full runtime
acceptance remain separate**. This page describes current code and accepted
boundaries. Dated task checkpoints and evidence records describe what was
verified at that time; they are not interchangeable with production readiness.

## Product and application structure

One backend replica serves shared EIA data to authorized clients. Amazon S3 owns
modeled Parquet, PostgreSQL on Amazon RDS owns operational records, Cognito owns
credentials, and DuckDB executes analytical reads. EC2 is the deployment target;
local development does not require an EC2 instance. See ADR-0001, ADR-0018,
ADR-0032 and [ADR-0038](../adr/0038-ec2-deployment-local-development.md).

[ADR-0030](../adr/0030-layered-flask-monolith.md) selects one layer-first product
codebase and release:

- `domain/`: pure modeling, retention, roles, publication and pagination policies.
- `application/`: authorization, use cases, transaction orchestration and ports.
- `infrastructure/`: EIA, Cognito, PostgreSQL, S3, Parquet, cache, SQL inspection,
  worker execution and result storage adapters.
- `entrypoints/`: thin HTTP, CLI and independently supervised worker entry points.
- `bootstrap.py`: concrete dependency construction and injection.

The [structure guide](code-structure.md) and [AGENTS.md](../../AGENTS.md) define
allowed dependencies. Flask factories register constructed services and perform
no ingestion, migrations, database queries or worker startup. Separately
supervised refresh and analytical workers remain part of this monolith.
The independent-services example in the [architecture study](../specs/outage-explorer-backend/architecture-options.md)
is an alternative, not the selected design.

The separate `outage-explorer-web` repository contains the Next.js/TypeScript UI,
session integration and live adapters. It is outside this repository's release.
The [UI handoff](ui-client/README.md) records its contract. Code presence and
user acceptance do not substitute for every outstanding integrated test.

## Source, model and durable data

EIA's national, facility and generator routes remain independent grains. Their
keys are respectively date, date/facility, and date/facility/generator. Contracts
and public columns live in `domain/datasets.py`, `domain/observations.py` and
`infrastructure/parquet/schemas.py`. The [verification contracts](../specs/facility-generator-verification/verification.md)
document bounded source evidence; they do not prove every historical schema.

The shared connector/refresh pipeline constructs exactly three unified resource
Parquet files per generation under [ADR-0060](../adr/0060-persist-only-three-resource-files-per-generation.md).
Physical files preserve private provenance, original numeric strings, units,
natural identity and exact calculation evidence. Raw pages, dispositions and
ledgers are bounded transient inputs. No durable supporting graph, S3 manifest,
daily modeled partitions or separate public-file copy is produced.

Physical keys follow [ADR-0061](../adr/0061-generation-prefixed-resource-object-keys.md):
`<configured-prefix>generations/<generation-id>/{national,facilities,generators}.parquet`.
Local immutable files use checksum identity instead. S3 conditional writes and
full readback establish an exact durable receipt. The receipt is not publication:
PostgreSQL stores exact descriptors and quality with the active-generation update.
Migration 0005 removes obsolete manifest columns and the old publication adapter
under [ADR-0064](../adr/0064-remove-obsolete-manifest-publication-columns.md).
Historical rows without exact resource descriptors fail closed; code never
silently converts them or clears publication history.

Pure policies collapse identical duplicates and choose the last valid source
record for within-retrieval conflicts. Refresh preserves older valid rows after
invalid replacements, absent keys and wholly excluded routes while allowing other
valid updates. All-excluded refreshes retain the active generation without
publication. Initial loading requires usable output in all three grains; the
accepted initial interval is April 2–October 1, 2026 inclusive
([ADR-0037](../adr/0037-connector-initial-load-and-retention.md)). Complete route
counts share one domain eligibility policy; streaming never reconstructs a
whole-history partition just to evaluate eligibility.

The national public dataset includes source and calculated outage percentages.
Calculation preserves precision; presentation uses two decimals and halfway-up
rounding. The metric is daily reported capacity out of service, including partial
reductions, not duration, lost energy or cause. See the
[national contract](../specs/national-data-verification/contract.md) and
[challenge findings](../challenge/README.md), including reproducible reconciliation
and three documented anomalies. Offline contributor commands replay recorded
inputs without live retrieval or publication.

## Authentication and authorization

`LoginService` and the Cognito adapter implement Authorization Code with PKCE,
bounded HTTPX exchanges and PyJWT access-token/JWKS verification. Authlib is not
a dependency. PostgreSQL contains seeded users, one role per user, application
sessions and browser-bound single-use login attempts. Provider roles and scopes
do not determine application permissions. Registration and Admin user management
are excluded (ADR-0043/0044).

Sessions default to a fixed one-hour lease without automatic renewal. Logout
invalidates only the current application session. Expired login attempts are
reclaimed before admission capacity checks under the same transaction lock;
explicit maintenance remains available. Cookie, Origin/CORS and sanitized error handling live at the HTTP boundary;
cryptographic CSRF validation uses the injected application/security seam. Application use cases independently
resolve current sessions and roles before analytical data access, including on
continuation requests. Viewer is national-only; Analyst/Admin can read all grains;
only Admin can initiate or inspect refresh.

IAM signing per physical PostgreSQL connection, confidential Cognito client
support and typed HTTP guards are implemented. The user accepted the web auth
integration; the [verification record](../specs/user-access/verification.md#subsequent-local-authentication-and-web-integration--2026-10-05)
distinguishes this and specific Viewer evidence from still-open comprehensive
live-persona/browser cases. Do not repeat the superseded claim that no login or
application integration exists. Controlled tests do not prove all live behavior.

## HTTP, analytical preparation and execution

HTTP refresh uses the configured start through today's UTC date, resolved at
admission and saved with the run. There is no fixed 183-day ceiling; all non-date
resource bounds and the explicit initial-load policy remain enforced under
[ADR-0063](../adr/0063-configured-start-current-end-refresh.md).

Opt-in data HTTP mounts seven operations: catalog, dataset preview, SQL submission
and retained paging, and refresh admission/latest/by-ID. Auth routes handle login,
callback, session and logout. See the implemented [HTTP contract](../specs/data-api/http-contract.md)
and [OpenAPI](../specs/data-api/openapi.json). Public dataset/SQL names are
`national`, `facilities` and `generators`. Preview supports date bounds and one
exact facility ID for facility/generator datasets; national is date-only. The
[facility-filter checkpoint](../specs/preview-facility-filter/tasks.md) records
verification limits and the required matching version-2 worker image/profile.
The [feature verification](../specs/preview-facility-filter/verification.md) separates
portable HTTP/worker acceptance from unavailable database and actual-host checks.

SQL inspection runs in a separate bounded subprocess under ADR-0054. Authentication
precedes inspection; complete reference authorization precedes analytical inputs.
The trusted cache downloads only approved exact resource files, streams misses
to temporary disk with byte/checksum checks, verifies schema/coverage and pins
entries against eviction. Workers receive exact staged files; DuckDB views
explicitly project public columns. Physical private columns are not queryable
through those views. There is no API-process DuckDB fallback or per-request
public-file reconstruction.

The implemented launcher/supervisor enforces configured lifecycle, admission,
transport and resource controls. Worker grants exclude operational PostgreSQL,
cloud credentials, network and unrelated cache paths. Ownership intent precedes
staging allocation; cleanup retains ownership until worker termination and
reclamation are confirmed. Linux quota storage and reviewed profile/image/evidence
checks are startup prerequisites. These mechanisms and controlled tests are not
blanket proof of production isolation or measured capacity.

SQL executes once into bounded private result storage. Numbered pages preserve
that execution's order, multiplicity and explicit clauses; no pagination SQL is
injected and no continuation silently reruns it. Metadata is process-owned and
in memory, never PostgreSQL. Preview and SQL sequences expire without renewal
at 60 seconds under [ADR-0059](../adr/0059-sixty-second-preview-result-lifetime-and-capacity.md).
Pages default to 100 and allow up to 500 rows; SQL output is capped at 1,000 rows
or 1 MiB with explicit truncation. Active readers and unresolved reaping prevent
premature release. Expiry/store loss requires an explicit new sequence.

## Refresh admission, execution and publication

Admin HTTP admission records the configured inclusive date range and frozen
settings; callers cannot override dates (ADR-0051). A separately supervised worker
claims runs with database-time leases, restores the pinned base, builds/verifies
the candidate, persists all three files, verifies exact durable identity, then
publishes descriptors and quality atomically through PostgreSQL. The previous
valid generation remains available on failure. API shutdown does not own refresh.

Publication and recovery are fenced against stale owners. A healthy worker
survives API-only restarts; lost-worker recovery reconciles committed publication.
Unpublished interrupted runs require explicit Admin retry, not automatic source
reruns (ADR-0052). There is no reset CLI, review queue or second publish action.
The [refresh-persistence checkpoint](../specs/refresh-persistence/tasks.md) and
[refresh recovery code](../../src/outage_explorer/application/services/refresh_recovery.py)
describe current implementation; infrastructure recovery/backup policy is distinct.

## Runtime scope and remaining evidence

ADR-0053 accepts one threaded API serving process, one analytical slot and
independent refresh for local analytical acceptance. Final EC2 process topology,
ingress/TLS, supervision, storage provisioning and capacity remain open.
[ADR-0055](../adr/0055-scoped-local-analytical-readiness.md) separates narrow local
readiness with refresh idle from full high-water/spill, S3 performance and overlap
acceptance. [ADR-0056](../adr/0056-user-directed-local-api-activation.md) records the
user's later local activation direction and instruction to stop further external
validation. Earlier unperformed checks remain evidence gaps, not a new request
to block or repeat activation.

Imports/factories remain inert. Without supplied reviewed runtime resources,
analytical forwarding ports fail closed; catalog and refresh have independent
prerequisites. Startup and shutdown are explicit and process-owned. No documentation
edit grants deployment, service startup, publication reset or cloud access.

The [runtime evidence map](../specs/data-api/runtime-evidence.md),
[analytical-worker runbook](../../infrastructure/analytical-worker/README.md) and
[user-access verification](../specs/user-access/verification.md) retain their
scoped and dated limitations. The five login-admission cleanup PostgreSQL cases
added during review have not run without an explicit disposable test DSN. General
snapshot deletion/backup recovery, broader historical source completeness and
production capacity remain open. This documentation update performs no runtime,
external-service or new database validation.
