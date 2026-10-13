# Refresh run ORM pilot

Scope: implement the selected synchronous SQLAlchemy repository pattern for
`RefreshStore.get_run` and `latest`, to evaluate readability and compatibility before
considering other persistence operations.

- Existing run IDs return the same complete domain `RefreshRun`; missing IDs
  return `None`. Each call observes fresh committed state.
- `latest` prioritizes the active run, then admission time descending and UUID
  descending. Missing coordination or no runs returns `None`, matching the
  existing join. A released active pointer is observed on the next call.
- SQLAlchemy models and sessions remain in infrastructure. Application callers
  receive plain domain values, usable after the session closes.
- `PostgresqlRefreshRunRepository` owns the ORM queries. The existing publication
  store delegates `get_run` and `latest` to this injected repository, preserving the
  `RefreshStore` interface. Bootstrap supplies both with the same bounded pool.
- The user-selected `@with_session` decorator owns the method's session scope
  and injects the session into both reads. `get_run` callers pass only `run_id`,
  positionally or by keyword; `latest` takes no arguments. Each call has its own transaction; decorated calls
  do not form a shared Unit of Work.
- ORM reads share the existing bounded, process-owned PostgreSQL pool, IAM
  credentials and timeouts with handwritten SQL. Do not add another physical
  connection pool or change the public HTTP contract.
- Database failures remain sanitized `AccessStoreError` failures. Close the
  session and return the connection on both success and failure.
- Admission, ownership, publication, recovery, access persistence, schema and
  migrations are unchanged. No live refresh, deployment or publication is needed.

Acceptance: PostgreSQL tests prove complete mapping, missing IDs, fresh reads,
coexistence with handwritten SQL, resource cleanup, process/closed-pool rejection
and sanitized failures. Existing refresh recovery and pool tests remain valid.
