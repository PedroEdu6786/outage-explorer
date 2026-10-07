# Decisions

This document consolidates the technical challenge's required decisions from
the project's ADRs, contracts and development journal. Reviewed October 6, 2026.
It records the selected behavior, alternatives and reasons; it does not replace
the historical ADRs or establish that an implementation/runtime gate has passed.
Later accepted ADRs take precedence over superseded details in earlier records.
Automatically captured devlog summaries are historical context, not independent
proof of approval or test results.

## Challenge coverage

| Required decision | Entry |
| --- | --- |
| Natural key for each grain | [D01](#d01-natural-keys-identify-observations-within-a-generation) |
| Meaning of current data and refresh behavior | [D02](#d02-current-data-is-the-last-successfully-published-generation) |
| Missing parent facilities and mismatched generator sums | [D03](#d03-preserve-independent-grains-and-report-reconciliation-gaps) |
| Synchronous versus asynchronous refresh | [D04](#d04-refresh-runs-in-an-independently-supervised-background-worker) |
| Supported and rejected SQL | [D05](#d05-offer-broad-read-only-analytical-sql-with-explicit-exclusions) |
| Discovering every table before permission checks | [D06](#d06-inspect-the-complete-sql-scope-before-analytical-access) |
| Additional consequential decision | [D07](#d07-separate-three-file-analytical-storage-from-operational-transactions); further choices in D08–D10 |

See the [data model and ER diagrams](docs/context/data-model.md) for schemas and
[FINDINGS.md](FINDINGS.md) for actual observations and reproducible reconciliation.

## D01: Natural keys identify observations within a generation

**Choice.** National: `period`; facility: `(period, facility)`; generator:
`(period, facility, generator)`. Identifiers remain opaque strings, preserving
leading zeros and alphanumeric values. A facility name is an attribute, not
identity. These keys are unique within each published generation.

**Alternatives rejected.** Date alone for detail observations would merge
different entities. Generator ID alone would merge generators at different
facilities. Names as keys would turn renames into new entities. Surrogate row
IDs alone would not detect repeated source observations.

**Why and consequences.** Recorded metadata and September observations support
these grains. Validate before selecting a winner: greatest recorded source
position wins among usable records for a key; equal earlier values are duplicates
and different earlier values are superseded. This deterministic fallback does
not prove upstream revision recency. Across refreshes, new valid values replace
old values; invalid replacements retain prior valid data. Parquet does not enforce
keys itself, so ingestion and verification own uniqueness.

**Basis:** [ADR-0024](docs/adr/0024-collapse-duplicates-and-use-latest-values.md),
[ADR-0034](docs/adr/0034-last-national-record-wins.md),
[ADR-0036](docs/adr/0036-extend-verification-to-facilities-and-generators.md),
[national contract](docs/specs/national-data-verification/contract.md),
[detail contracts](docs/specs/facility-generator-verification/contract.md).
The [October 2 journal](docs/devlog/2026-10-02.md) records the shared validation,
source-order selection and three-grain verification work.

## D02: Current data is the last successfully published generation

**Choice.** Product reads use the backend's last durably verified and published
generation, independently of EIA availability after ingestion. Current does not
mean fetched from EIA on each request, nor does a successful refresh imply that
every retained observation was freshly retrieved.

Initial loading uses April 2–October 1, 2026 inclusive. Product HTTP refresh
uses a configured inclusive interval for all three grains; callers cannot override
dates. Resolve and freeze that configuration at admission. Connector CLI runs
retain explicit bounded date overrides. There is no automatic rolling window
or refresh schedule.

**Alternatives rejected.** Per-request EIA reads would couple availability and
latency to the upstream service. A rolling latest-30-day default was an early
proposal, replaced by explicit/configured intervals. Blind interval replacement
would discard valid observations when a key is absent or its new value is invalid.

**Why and consequences.** Preserve availability and reproducibility while allowing
valid corrections. Retain absent prior keys, invalid replacements, observations
outside the refreshed interval, and complete prior datasets when one route's
nonempty input is wholly excluded. Other valid updates can publish. If all
incoming rows are excluded, retain the active generation and report no publication.
Initial publication requires usable output in all three grains. Failed pages,
empty required routes and integrity failures remain run failures.

Previous data stays active while a refresh runs or fails. Successful publication
activates the complete generation automatically; existing readers remain bound
to their original snapshot until completion or explicit expiry. Quality outcomes
distinguish new rows from retained rows and preserve retained provenance.
Corrections outside the configured interval are not discovered automatically.

**Basis:** [ADR-0003](docs/adr/0003-admin-refresh-publication.md),
[ADR-0026](docs/adr/0026-retain-valid-data-on-invalid-refresh.md),
[ADR-0037](docs/adr/0037-connector-initial-load-and-retention.md),
[ADR-0051](docs/adr/0051-configured-http-refresh-range.md).
ADR-0037 explicitly resolves earlier devlog agreements; the
[October 2 journal](docs/devlog/2026-10-02.md) records retained-data connector work.

## D03: Preserve independent grains and report reconciliation gaps

**Choice.** Keep valid national, facility and generator observations independently.
Relationships between their Parquet datasets are logical joins, not enforced
foreign keys. A usable generator observation without a matching facility/day
observation remains a generator observation; do not synthesize its parent or
silently delete it. This follows the existing independent-grain model and
per-grain validation contracts, rather than adding a new parent-existence rule.

Compare generator sums with facility values on `(period, facility)`, and facility
sums with national values on `period`. Preserve missing matches and actual
capacity/outage differences with their dates, identifiers, values and gaps.
Use outer joins for coverage investigations. Do not overwrite reported facility
or national values to force agreement. The national source remains the fleet
metric's input.

**Alternatives rejected.** Inner joins alone can hide unmatched observations.
Rejecting all children of an absent parent discards independently usable source
data. Fabricating parents or replacing reported totals with sums hides the
discrepancy we need to explain. Summing percentages does not reconcile MW values.

**Why and consequences.** The source grains must remain inspectable and their
differences reproducible. Missing-parent cases describe handling, not an observed
anomaly in the recorded baseline. September's 30-day reconciliation has zero
capacity/outage gaps across the recorded grains; that does not prove upstream
completeness. The facility advertised-total mismatch is a separate metadata
discrepancy: count actual received rows and preserve the advertised total separately.

**Basis:** [ADR-0002](docs/adr/0002-analytical-dataset-contracts.md),
[ADR-0036](docs/adr/0036-extend-verification-to-facilities-and-generators.md),
[detail contracts](docs/specs/facility-generator-verification/contract.md),
[Finding 001](docs/challenge/001-facility-row-count.md).
The [October 3 journal](docs/devlog/2026-10-03.md) records both the exact
reconciliation and the user's accepted received-row accounting decision.

## D04: Refresh runs in an independently supervised background worker

**Choice.** Admin admits a refresh through HTTP and polls its durable outcome.
The worker runs outside HTTP request, import and application-factory lifecycles.
A healthy worker survives browser disconnects and API-only restarts. Successful
verification and persistence lead to automatic publication; there is no separate
candidate approval or publish action.

**Alternatives rejected.** Holding an HTTP request open for the whole refresh
ties long-running work to connection lifetimes. An in-process request task does
not provide API-restart independence. A broker or separate network service adds
components without an accepted need. Manual candidate approval adds an excluded
product workflow.

**Why and consequences.** Source retrieval, modeling and durable verification
take longer than admission and need durable ownership. After worker loss,
reconcile publication before deciding the outcome. An unpublished interrupted
run requires explicit Admin retry; automatic source reruns are excluded. Stale
owners must be fenced from publication, and uncertain commits cannot be reported
as confirmed failures or successes merely from a lost connection.

**Basis:** [ADR-0003](docs/adr/0003-admin-refresh-publication.md),
[ADR-0030](docs/adr/0030-layered-flask-monolith.md),
[ADR-0052](docs/adr/0052-interrupted-refresh-recovery.md),
[HTTP refresh contract](docs/specs/data-api/http-contract.md#background-refresh).
The [October 4 journal](docs/devlog/2026-10-04.md) records data-API contract and
supervised refresh integration work.

## D05: Offer broad read-only analytical SQL with explicit exclusions

**Choice.** Target read-only DuckDB analysis over public `national`, `facilities`
and `generators` views: filtering, joins, CTEs, nested subqueries, aggregations,
window functions and set operations. Reference-free analytical expressions are
also inspected and authorized. Execute submitted SQL unchanged.

Reject multiple statements, writes, DDL, configuration/admin commands, external
file/network access, extension loading, engine internals, unknown relations,
unapproved functions and unresolved access. The implementation validates AST
forms, scoped relations and a safe-function registry. Acceptance of broad SQL
does not establish support for every function or syntax form in DuckDB; parser
incompatibilities and unapproved functions fail closed and require explicit review.

**Alternatives rejected.** A single-table-only language would meet the challenge's
minimum but contradict the user's accepted exploration scope. Arbitrary DuckDB
commands would violate read-only access and isolation. Silently rewriting queries
or injecting pagination clauses could change the requested result.

**Why and consequences.** Analysts can compose investigations while authorization
and resource bounds remain enforceable. Admit one analytical execution at a time,
with the accepted ten-second execution ceiling and a retained output cap of
1,000 rows or 1 MiB, with explicit truncation. Pagination reads the same retained
execution; it never silently reruns SQL. Resource caps are not proof that every
query will complete, and complete compatibility/runtime acceptance remains separate.

**Basis:** [ADR-0012](docs/adr/0012-duckdb-analytical-feature-scope.md),
[ADR-0013](docs/adr/0013-initial-query-controls.md),
[ADR-0020](docs/adr/0020-paginate-query-results.md),
[SQL inspector](src/outage_explorer/infrastructure/sql_validation/inspection.py),
[safe functions](src/outage_explorer/infrastructure/sql_validation/functions.py).
The [October 1 journal](docs/devlog/2026-10-01.md) records the user's broad
read-only exploration direction; later implementation does not imply universal
DuckDB compatibility.

## D06: Inspect the complete SQL scope before analytical access

**Choice.** Authenticate first. Parse and inspect SQL in a separately bounded
subprocess, then authorize every discovered product dataset in the application
use case before resolving the active generation, preparing files or executing SQL.
The subprocess receives SQL and fixed settings, without sessions, analytical
inputs or operational/cloud credentials. There is no API-process parsing fallback.

Resolve scoped table references throughout joins, CTEs and nested subqueries;
distinguish CTE aliases from physical datasets. Reject qualified/unknown relations
and any table node not accounted for by scope traversal. Inspect functions as
well as table names, since functions can introduce data access. The analytical
worker reinspects SQL as an additional defense and receives only authorized files.

**Alternatives rejected.** Checking the first table, a `SELECT` prefix or regex
matches misses nested access and alias shadowing. Relying on UI visibility or
route decorators alone permits direct/use-case bypasses. API-process parsing
with byte/AST limits alone cannot enforce parser CPU, memory and time limits.

**Why and consequences.** Viewer restrictions apply to every reference, including
hidden/nested ones, before analytical I/O. Unknown access fails closed. Subsequent
result pages check current local authorization and result ownership again. Parser
and worker lifecycle enforcement must confirm termination before capacity is
released; source inspection alone does not prove native isolation.

**Basis:** [ADR-0043](docs/adr/0043-seeded-users-and-role-only-access.md),
[ADR-0054](docs/adr/0054-bounded-subprocess-sql-inspection.md),
[SQL inspector](src/outage_explorer/infrastructure/sql_validation/inspection.py),
[query use case](src/outage_explorer/application/services/queries.py).
The [October 6 journal](docs/devlog/2026-10-06.md) records the accepted subprocess
boundary and subsequent scoped runtime review/activation; broader evidence gates
remain distinct from local activation.

## D07: Separate three-file analytical storage from operational transactions

**Choice.** Persist exactly three unified Parquet resources per generation in S3,
one per grain. Keep original numeric strings, units, natural identity, provenance
and exact calculation evidence as private columns. DuckDB scans staged files
through views projecting only public columns. PostgreSQL stores exact resource
descriptors, quality summaries, refresh state and the active-generation pointer.

Verify durable file readback before committing publication metadata and successful
run state together in PostgreSQL. An S3 receipt alone is not publication. Physical
keys follow `<prefix>generations/<generation-id>/{national,facilities,generators}.parquet`.

**Alternatives rejected.** Daily modeled partitions and separate modeled/public
files multiply objects and transfer work. Persisting all raw/page/disposition/ledger
artifacts is unnecessary for subsequent baseline merges under the accepted scope.
An S3 manifest duplicates publication metadata now owned by PostgreSQL. Importing
entire inputs into DuckDB tables adds whole-input materialization.

**Why and consequences.** Reduce object/transfer overhead while retaining faithful
baseline merges and public schemas. Supporting candidate evidence is bounded and
transient; selected recorded findings remain separate reproducible evidence.
Estimated operation savings are not measured performance guarantees. Obsolete
manifest publication columns and the previous adapter are removed by migration
0005 under ADR-0064. An active generation without exact resource descriptors
fails closed for resource readers; no automatic conversion,
history rewrite or pointer reset is authorized. Shared composition and managed
rollout remain subject to their implementation checkpoints.
Refresh-run metadata is also simplified under ADR-0065: idempotency uses
requester/key in the refresh-only table, without constant operation/request
identity or unused update timestamps. Replays preserve the admitted snapshot.

**Basis:** [ADR-0001](docs/adr/0001-s3-parquet-duckdb.md),
[ADR-0032](docs/adr/0032-postgresql-on-rds.md),
[ADR-0060](docs/adr/0060-persist-only-three-resource-files-per-generation.md),
[ADR-0061](docs/adr/0061-generation-prefixed-resource-object-keys.md),
[ADR-0062](docs/adr/0062-fail-closed-legacy-publication-layout.md),
[ADR-0064](docs/adr/0064-remove-obsolete-manifest-publication-columns.md),
[ADR-0065](docs/adr/0065-simplify-refresh-run-idempotency-and-metadata.md).
The [October 6 journal](docs/devlog/2026-10-06.md) records the three-file direction,
phase checkpoints and explicit fail-closed selection for the old active layout.

## D08: Calculate the fleet metric from national capacity and outage values

**Choice.** Daily fleet offline share is `outage / capacity`; percentage is that
exact rational value multiplied by 100, from the selected national observation.
Require positive capacity and finite source decimals. Preserve reported and
calculated percentages; display both to two decimals using half-up rounding.

**Alternatives rejected.** Averaging generator/facility percentages weights entities
incorrectly. Replacing national inputs with detail sums changes the source grain.
Binary floating point loses exact decimal evidence. Rejecting a row merely because
reported and calculated percentages differ adds an excluded agreement policy.

**Why and consequences.** The metric describes EIA-reported capacity out of
service, including full outages and partial reductions. It does not establish
outage duration, lost energy or the proportion of reactors fully shut down.
Store the prepared metric in `national`, rather than adding a fourth dataset.

**Basis:** [ADR-0006](docs/adr/0006-daily-fleet-offline-share.md),
[ADR-0031](docs/adr/0031-show-national-percentages-without-discrepancy-flags.md),
[ADR-0035](docs/adr/0035-national-outage-capacity-meaning.md),
[national contract](docs/specs/national-data-verification/contract.md).
The [October 1](docs/devlog/2026-10-01.md) and
[October 2 journals](docs/devlog/2026-10-02.md) record national verification and
its extension to detail observations.

## D09: Cognito establishes identity; PostgreSQL owns role-only access

**Choice.** Use Cognito managed login with OAuth2 Authorization Code and PKCE.
Link verified issuer/subject to a seeded local user with exactly one role.
Viewer can access national data; Analyst/Admin can access all analytical grains;
only Admin can refresh or read protected refresh diagnostics. Enforce current
local policy on protected use cases and subsequent pages.

**Alternatives rejected.** Provider groups/scopes or email alone cannot grant
application permissions. Local password storage duplicates the provider's
responsibility. Registration, Admin user management, individual grants and
granular read/write/delete or ABAC policy add excluded scope.

**Why and consequences.** Keep one application-owned authorization authority
across UI and direct API access. Unlinked/unassigned identities fail closed;
provider authentication alone is insufficient. PostgreSQL persistence does not
make query-ID metadata durable; retained query continuations remain ephemeral.

**Basis:** [ADR-0018](docs/adr/0018-cognito-authentication.md),
[ADR-0032](docs/adr/0032-postgresql-on-rds.md),
[ADR-0043](docs/adr/0043-seeded-users-and-role-only-access.md),
[ADR-0044](docs/adr/0044-one-role-per-user.md),
[ADR-0022](docs/adr/0022-ephemeral-query-pagination-state.md).
The [October 5 journal](docs/devlog/2026-10-05.md) and
[user-access verification](docs/specs/user-access/verification.md) distinguish
controlled checks, user-confirmed integration and remaining live evidence.

## D10: Keep a layered Flask monolith with explicit process boundaries

**Choice.** One backend product/release uses `domain`, `application`,
`infrastructure` and thin `entrypoints`, wired in `bootstrap.py`. Separate
refresh supervision and isolated analytical/parser workers remain implementation
boundaries within that product. The web client is a separate codebase. EC2 is
the selected deployment target; development does not require an EC2 instance.

**Alternatives rejected.** The earlier feature-first structure, FastAPI and ECS
proposals were replaced. Microservices, service-to-service HTTP or a broker add
operational boundaries without a demonstrated requirement. Business/storage logic
in Flask routes would bypass reusable use-case policy and complicate verification.

**Why and consequences.** Keep authorization and pure policies testable while
isolating I/O and untrusted execution. Local acceptance uses one API process
with threads and one analytical slot; this does not settle final EC2 topology.
Documentation, local activation and controlled tests do not establish deployment
or complete capacity acceptance.

**Basis:** [ADR-0028](docs/adr/0028-python-flask-backend.md),
[ADR-0030](docs/adr/0030-layered-flask-monolith.md),
[ADR-0038](docs/adr/0038-ec2-deployment-local-development.md),
[ADR-0039](docs/adr/0039-separate-ui-client-atomic-design.md),
[ADR-0053](docs/adr/0053-local-single-owner-analytical-acceptance.md).
The [October 1 journal](docs/devlog/2026-10-01.md) records architecture evolution;
the [October 6 journal](docs/devlog/2026-10-06.md) records local topology decisions.

## Limits of this decision summary

Proposed ADRs are not silently promoted by this document. In particular,
ADR-0046/0047 integration/tooling and ADR-0059 lifetime wording retain their
recorded status; current code/contracts and evidence describe implementation
separately. Historical SQLite, ECS, six-file and manifest descriptions are read
with their accepted superseding decisions above.

The [refresh-persistence checkpoint list](docs/specs/refresh-persistence/tasks.md)
tracks the three-file rollout. The [runtime evidence](docs/specs/data-api/runtime-evidence.md)
separates local activation from remaining full acceptance. [FINDINGS.md](FINDINGS.md)
still needs two further real anomalies. This consolidation changes no architecture,
data, runtime settings, publication history or acceptance result.
