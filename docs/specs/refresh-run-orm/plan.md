# Refresh run ORM pilot plan

1. Map the existing `refresh_runs` columns with typed SQLAlchemy declarations
   and explicit keyword-based conversion to `RefreshRun`. The mapping is for
   querying, not a replacement schema definition for Alembic autogeneration.
2. Add short-lived ORM sessions to the existing PostgreSQL resource owner.
   SQLAlchemy uses NullPool and psycopg's close-returns integration. Set tuple
   rows for ORM checkouts and restore dictionary rows before pool reuse.
3. Replace the public `get_run` and `latest` queries with mapped reads. Preserve the
   existing repository interface and transaction-scoped SQL helpers.
   Put the ORM query in `PostgresqlRefreshRunRepository`; inject it into the
   publication store from bootstrap and delegate both existing read methods.
   For `latest`, join a partial coordination mapping and preserve active-first,
   timestamp-descending and UUID-descending ordering, including missing-row behavior.
   Use the typed infrastructure `@with_session` decorator to inject the session
   and keep lifecycle code outside the method body. Its context delegates to the
   existing pool session wrapper for commit/rollback, cleanup and error mapping.
4. Exercise the adapter against disposable PostgreSQL, including concurrent
   ORM/raw reads and reuse after failure; run static and architecture checks.

This pilot does not establish ORM suitability for the write/locking/recovery
paths. Those need separate acceptance before expansion. No generic repository
base class or additional application abstraction is needed.
