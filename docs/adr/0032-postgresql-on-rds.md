# ADR-0032: Use PostgreSQL on Amazon RDS for operational data

Status: **Accepted by user direction**

Date: 2026-10-01

Supersedes: [ADR-0005](0005-sqlite-on-aws.md). Replaces the SQLite-specific
EC2/EBS storage proposal in [ADR-0011](0011-ecs-hosting.md); ECS remains selected
and its launch type remains open.

## Context

SQLite was chosen for one backend replica without a separate database server.
With ECS hosting, that choice required managing a durable database file,
volume attachment, and recovery outside disposable application containers.
The user accepted the recommendation to use PostgreSQL on Amazon RDS instead.

## Decision

Use **Amazon RDS for PostgreSQL** as the durable operational database. It owns
local identity mappings, application permissions and policy attributes,
application-session state, refresh runs and quality outcomes, trusted catalog
metadata, and the active-generation reference, as required by the existing
contracts. Cognito continues to own login credentials and token issuance.

Keep the layered Flask monolith and one active backend replica. Concrete database
adapters belong in `infrastructure/postgresql/`, implementing application-owned
ports. Application use cases define transaction boundaries. Use PostgreSQL for
local integration tests and development as well; pure unit tests can use fakes.
Select and pin the version, Python driver/ORM, migration tool, and local setup
during implementation.

Operational storage runs independently of ECS task and host lifecycles. The
backend connects to RDS; it does not mount a live database file. This removes
the SQLite-driven host-managed EBS requirement. It does not select Fargate,
resolve the SQL sandbox launcher, authorize extra replicas, or change ephemeral
query-state ownership.

## Boundaries and consequences

- Raw/modeled outage data remains Parquet in S3, queried with isolated DuckDB
  workers and the bounded local cache. User SQL cannot access PostgreSQL.
- Query-ID metadata remains bounded, expiring, and in-memory under ADR-0022;
  choosing PostgreSQL does not make query continuations durable.
- Commit publication metadata and successful run state in one short PostgreSQL
  transaction after verifying candidate uploads. S3 writes are outside that
  transaction. Preserve single-refresh ownership, reader pinning, idempotency,
  and recovery after uncertain commit outcomes.
- Design private database connectivity, verified TLS, credential handling,
  bounded connection pools, connection/statement/lock timeouts, and serialized
  migrations. Analytical workers receive no operational database credentials
  or network access. Exact networking, roles, and operational settings remain
  implementation decisions.
- Managed database hosting adds cost and a network dependency. RDS offers
  backup/restore and availability features; choosing the service does not
  configure those features or establish an availability/recovery guarantee.
  Instance sizing, Single-AZ/Multi-AZ, retention, recovery objectives, and
  maintenance settings remain open; deferred recovery-policy work stays deferred.

## Alternatives considered

- **SQLite:** valid for the earlier topology, but retains database-file ownership
  and volume lifecycle responsibilities alongside ECS.
- **MySQL on RDS:** also meets the current operational-data requirements. No
  PostgreSQL-only feature is necessary for the choice; the user selected the
  proposed PostgreSQL direction.
- **Self-managed PostgreSQL:** retains database-server administration work;
  the accepted recommendation is managed RDS hosting.

## Verification and implementation status

No application database, migration, or AWS resource exists from this work.
There is no existing SQLite data to migrate. This decision updates documentation
and agent guidance only.

Implementation must verify migrations and constraints against real PostgreSQL,
publication rollback and uncertain commits, competing refresh claims,
connection exhaustion/recovery, current-session logout, and ECS replacement
without re-ingestion. Database availability failure must not bypass authorization
or report an unverified publication as successful.

Historical ADRs and council records retain their original SQLite references;
this decision replaces the engine choice while preserving their applicable
application-owned authorization and lifecycle requirements.

## References

- [Amazon RDS for PostgreSQL](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html)
- [RDS PostgreSQL TLS connections](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html)
- [Layered monolith structure](../context/code-structure.md)
