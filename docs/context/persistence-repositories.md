# Required persistence repository pattern

[ADR-0078](../adr/0078-model-repositories-and-session-decorators.md) establishes
this convention for new and refactored operational PostgreSQL persistence.
Read it before adding model queries or changing persistence/process boundaries.

## Responsibilities and location

| Component | Responsibility | Location |
| --- | --- | --- |
| Domain value, e.g. `RefreshRun` | Domain meaning and rules, without database dependencies | `domain/` |
| ORM record, e.g. `RefreshRunRecord` | Table/column mapping and conversion to domain values | `infrastructure/postgresql/*_record.py` |
| Repository, e.g. `PostgresqlRefreshRunRepository` | Central home for queries involving its model or cohesive model concern | `infrastructure/postgresql/*_repository.py` |
| `@with_session` | Inject a per-operation session using the existing lifecycle wrapper | `infrastructure/postgresql/session_scope.py` |
| `@with_session_context` | Hold an injected session across a repository transaction context | `infrastructure/postgresql/session_scope.py` |
| Service/process coordinator | Decide the workflow and invoke persistence operations through the allowed interfaces | Existing application/infrastructure layer, according to the dependency matrix |
| Bootstrap | Construct repositories and inject them with the shared bounded pool | `bootstrap.py` |

## Required implementation

- MUST centralize model queries in the appropriate repository. Extend that
  repository for related queries instead of scattering them through process code.
- MUST use SQLAlchemy ORM/expressions and `@with_session` for ordinary repository
  operation boundaries. The repository method queries/maps; the decorator owns
  the session scope through `BoundedPostgresqlPool.session()`.
- MUST return plain domain values or application DTOs, fully materialized before
  leaving the session. Keep ORM imports and session objects out of domain and
  application code.
- MUST keep workflow decisions separate from query construction/execution.
  Process logic calls repository operations; it does not embed raw SQL or inline
  ORM queries. Existing store interfaces may delegate to injected repositories
  to preserve their application contracts during migration.
- MUST preserve authorization-before-access, transaction atomicity, existing
  connection bounds, fresh state per operation, error sanitization and cleanup.
- MUST NOT introduce generic CRUD base classes or a repository per table without
  a cohesive query responsibility. Related model joins belong with the operation
  they serve; `latest()` is an example.

## Reference implementation

From [refresh_run_repository.py](../../src/outage_explorer/infrastructure/postgresql/refresh_run_repository.py):

```python
class PostgresqlRefreshRunRepository:
    def __init__(self, pool: BoundedPostgresqlPool) -> None:
        self._pool = pool

    @with_session
    def get_run(self, session: Session, run_id: str) -> RefreshRun | None:
        record = session.get(RefreshRunRecord, run_id)
        return record.to_domain() if record is not None else None
```

Callers use `repository.get_run(run_id)`; they do not supply a session.
`RefreshRunRecord` declares persistence mapping. The repository is the place to
add queries. Application callers depend on their application-owned port, not the
concrete SQLAlchemy repository. The existing publication store delegates its
read methods to this repository.

## Transactions

Each `@with_session` call opens its own transaction. Multiple such calls do not
become atomic simply because one process method invokes them together.
`@with_session_context` differs: entering its returned context opens the
session, and exiting that context commits or rolls back. It is for a focused
transaction port whose caller must decide between locked reads and writes.

Keep a multi-table atomic database operation within one shared session. Its
internal query helpers take that session instead of opening new ones. Preserve
the application-owned transaction requirement through the operation's port;
do not expose SQLAlchemy sessions to application code. Publication's generation,
pointer and successful run update must still commit together. Heartbeats use
independent sessions; external source/storage work stays outside transactions.

## Existing code and limited SQL cases

`get_run()`, `latest()`, replay, claim, heartbeat, progress, unpublished finish
and generation publication use the decorated pattern. Admission holds one
repository-owned session and coordination lock across the application service's
replay, busy-slot and initial-load decisions. The service invokes pure domain
policy through a focused transaction port; the repository only queries and
writes the queued run and slot. Its repository operation uses
`@with_session_context`; separate `@with_session` calls would split the
transaction. Each ownership write locks
`refresh_coordination` and completes within one decorated transaction.
Heartbeat, progress and finish share the same fenced
ownership check. Finish updates the run and releases the slot atomically.
`PostgresqlPublishedGenerationRepository.publish` uses one ORM transaction for
the immutable descriptor insert, run outcome, pointer switch and slot release.
Its ORM base check shares that session. Admission uses the same base-check
helper with its own locked ORM session. Uncertain publication commits still
reconcile through a fresh, locked checkout.
`active_generation` uses its own decorated ORM read over the active pointer and
returns a validated domain generation, or `None` when no generation is active.
`generation_for_run` likewise reads published history through a decorated ORM
query and returns a validated domain generation, or `None` when that run has no
publication.
The repository rechecks the base under its lock, then calls the pure
`domain.publication_policy.require_publishable_base` rule with domain values.
The rule decides base eligibility and initial-load start validity; the
repository maps a changed-base result to the existing stale-owner error.
`PostgresqlPublishedGenerationRepository.reconcile` locks coordination, checks
publication history, updates the run and releases the slot in one decorated ORM
transaction. The pure domain interruption rule decides when an unpublished
active run may be interrupted. A fresh checkout is required after an uncertain
publication commit. Finish and publication also release their slots within
their own decorated ORM transactions.
Other raw queries remaining in `publication.py` and `access.py` are legacy
implementation, not examples to copy.
Migrate them only as part of the requested scope, retaining their observable
behavior and atomicity. Documentation of this convention is not a bulk migration.

SQL in Alembic migrations and connection setup is outside model-query workflow
logic. User SQL and analytical adapters retain their separate isolation rules.
If a future operational query needs a database-specific raw statement, document
the concrete reason and contain it in the responsible repository; never embed
it in the process coordinator.

Partial ORM metadata in `orm_base.py` does not define the complete schema.
Alembic remains authoritative; do not use `create_all` or enable autogeneration
from these mappings.

## Review checks

Verify that queries have one clear repository home, process methods only invoke
persistence operations, session ownership is explicit, and return values remain
usable after cleanup. Run the relevant PostgreSQL tests for ordering, mapping,
concurrency, failures and atomicity, plus static and import-boundary checks.
Those existing checks do not automatically detect every SQL/process-mixing
violation; code review must apply this convention as well.
