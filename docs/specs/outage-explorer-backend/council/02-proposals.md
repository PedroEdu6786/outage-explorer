# Outage Explorer — Proposals

All proposals were authored independently from `../spec.md`. These are council recommendations, not user-approved architecture. This record summarizes each author's returned design and preserves its admitted risks.

**Subsequent user decisions:** These original proposals assumed too narrow a laptop-only environment. D10 corrected shared deployment and D11 selected one backend replica. SQLite/persistent attached storage/refresh ownership remain proposed mechanisms for that scope. Original proposals below are retained as history, not renewed acceptance.

## Proposal A — Python and isolated DuckDB (author: rafachafa, Pragmatist)
- **Approach:** Python, FastAPI, HTTPX, PyArrow, DuckDB, SQLGlot, SQLite, pytest. One backend/connector application; disposable local Docker containers execute analytical SQL without becoming a separate network service.
- **Authentication:** Three seeded SQLite users with Argon2 password hashes; random opaque bearer sessions stored as digests with expiry, server-side role lookup. Identity data never enters the analytical worker.
- **SQL:** SQLGlot DuckDB-dialect parsing and nested scope resolution; authorize all physical product relations, distinguish CTE aliases, execute validated re-emitted SQL. Support FR9's joins, nonrecursive CTEs, nested queries, aggregation and windows. Reject unrecognized nodes/functions, dynamic SQL, arbitrary table functions, external/metadata references, writes and multiple statements. Parser validation is not the sole security boundary.
- **Isolation:** Container receives only role-permitted modeled Parquet, no network, secrets, host home, or Docker socket; read-only root and bounded temporary storage, memory/CPU and wall time. Trusted bootstrap materializes allowed tables, then disables external access and extensions and locks settings before user execution. Proposed initial limits: one query at a time, 10 seconds execution, 1,000 rows, bounded response bytes, 1 GiB container memory; measurement required.
- **Refresh:** Explicit inclusive interval, staged fetch/validation of all routes. Merge into prior snapshot only after investigation establishes revision/deletion semantics. Atomically publish a complete snapshot; existing readers pin their version. Show coverage, retrieval time, counts and failures. Pin findings' input snapshots; otherwise retain current/previous plus active-reader snapshots. No scheduler or freshness SLA proposed.
- **Phase outline:** Source and isolation feasibility; ingestion/model/findings; identity/catalog/preview/SQL; publication and adversarial checks.
- **Data-model changes:** Three verified grain datasets, raw and modeled Parquet, manifests recording source parameters/times/hashes/counts/transformation version; source-verified metric; findings tied to snapshot IDs and queries.
- **Explicitly cut:** Auth/database servers, queues, scheduler, cache, frontend, generic policy engine.
- **Author-admitted risks:** Container startup, duplicated memory, SQLGlot/DuckDB interpretation differences, insufficient actual anomaly evidence, revision ambiguity, unconfirmed Docker availability. Never silently reduce FR9 if feasibility fails.
- **Traces to:** FR1–FR14, TR1–TR7, AC1–AC12.

## Proposal B — Rust with DataFusion (author: gamachiel, Architect)
- **Approach:** Rust, Axum/Tokio, reqwest, Arrow/Parquet, DataFusion, SQLite/rusqlite. Modular application with a request-scoped analytical catalog and containerized query execution.
- **Authentication:** Argon2id passwords and opaque expiring sessions; role resolved server-side, shared operation policy. Identity database excluded from analytical catalog. Loopback-only runtime proposed.
- **SQL:** Use DataFusion's parser, statement/reference-resolution APIs and planner rather than two independently interpreting parsers. Accept one query AST; recursively inspect all nodes including unused CTEs. Authorize all base relations before planning/opening Parquet. Register only role-permitted datasets; disable information-schema/dynamic providers and omit user functions/network facilities. Inspect logical operators and expression subqueries before physical execution. Reject generic SQL paths capable of DDL. Verification must prove resolver completeness; API availability is not proof.
- **Isolation:** Linux containers with role-scoped read-only inputs, no network/secrets, memory/CPU/wall limits and bounded output/concurrency. Engine memory accounting is additional protection, not a replacement for container limits.
- **Refresh:** Return durable run ID; one local background ingestion task rebuilds configured coverage across all grains, validates and atomically publishes a generation. Old readers/cursors pin generation. Retain current/previous and findings-pinned generations. Outcome distinguishes requested and returned coverage.
- **Phase outline:** Source and SQL/isolation feasibility; ingestion/publication/model/evidence; auth/backend; resource/failure tests and clean-host rehearsal.
- **Data-model changes:** Three source-verified datasets, immutable raw/modeled Parquet generations, coverage/schema/hash/validation/transformation manifests, identity/session/run metadata.
- **Explicitly cut:** Frontend, external identity, distributed workers, scheduler, cache, Delta.
- **Author-admitted risks:** Rust build/live-debugging learning costs, parser traversal, provider registration, incomplete memory accounting, container startup, actual data unknowns.
- **Traces to:** FR1–FR14, TR1–TR7, AC1–AC12.

## Proposal C — Exploration first on Python (author: kings, Product)
- **Approach:** Python/FastAPI/HTTPX/PyArrow/DuckDB/SQLGlot/SQLite/pytest, plain Parquet. First useful slice is authenticated exploration over real data; required findings are examples, not a fixed workflow.
- **Authentication/SQL/isolation:** Same independently proposed mechanisms as A: Argon2 and opaque sessions; authorize nested SQLGlot scopes for broad FR9 forms; audited function/node surface; container with role-limited data, no network/secrets, locked DuckDB settings, time/memory/CPU/rows/byte bounds. Nonrecursive CTEs initially.
- **Refresh:** Synchronous serialized refresh for an explicit date interval. Stage all routes and atomically publish; pin readers and pagination tokens. Return run ID, requested/actual coverage, counts, validation and snapshot ID; outcomes remain retrievable after disconnect. Freshness means visible coverage/retrieval time, not an implied SLA.
- **Phase outline:** Source and confinement feasibility; seeded login/catalog/preview/broad SQL on a verified snapshot; reconciliation/metric/findings; refresh and failure/security/reproduction tests. Notes and incremental commits from the beginning.
- **Data-model changes:** Immutable raw/modeled Parquet snapshots with verified schemas/keys, coverage, times, validation and hashes. Findings pin source snapshots, queries, observed values and hypotheses. Retain all evidence-pinned snapshots.
- **Explicitly cut:** Frontend, scheduler, external identity, cache, distributed services.
- **Author-admitted risks:** Parser/engine mismatch, container startup, revision semantics, confinement portability; benchmark before final limits and never reduce FR9 silently.
- **Traces to:** FR1–FR14, TR1–TR7, AC1–AC12.

## Source basis and limits
- [DuckDB SQL](https://duckdb.org/docs/current/sql/introduction) and [window functions](https://duckdb.org/docs/current/sql/functions/window_functions): analytical engine capability; application acceptance still needs tests.
- [DuckDB security](https://duckdb.org/docs/current/operations_manual/securing_duckdb/overview): engine settings alone do not replace isolation for untrusted SQL.
- [SQLGlot scope implementation](https://github.com/tobymao/sqlglot/blob/main/sqlglot/optimizer/scope.py) and [AST primer](https://github.com/tobymao/sqlglot/blob/main/posts/ast_primer.md): scope-aware relation discovery foundations, not a ready-made security policy.
- [FastAPI security](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/): password-hashing integration. Opaque sessions above are the authors' application design, not a claim that this JWT tutorial implements them.
- [Docker resource limits](https://docs.docker.com/engine/containers/resource_constraints/) and [network isolation](https://docs.docker.com/engine/network/drivers/none/): capabilities whose actual configuration must be verified.
- [DataFusion SELECT](https://datafusion.apache.org/user-guide/sql/select.html), [subqueries](https://datafusion.apache.org/user-guide/sql/subqueries.html), [SessionState](https://docs.rs/datafusion/latest/datafusion/execution/session_state/struct.SessionState.html), [memory pool](https://docs.rs/datafusion/latest/datafusion/execution/memory_pool/struct.GreedyMemoryPool.html): proposal B's capability basis, not a sandbox guarantee.

## Outcome
- **Selected recommendation:** A's Python application and isolation approach, C's exploratory delivery slice after a real-data gate, and B's transactional publication/run-outcome refinement. Two debate rounds converged; no blocking design objection remains. User approval and empirical feasibility remain open.
- **Proposal B not selected:** Its same-parser advantage is real, but it does not discharge complete reference/function validation or sandbox proof. gamachiel conceded that Rust has no independent requirement trace here; retained dissent is in D1. Revisit only if the recommended parser/engine combination cannot meet FR9/FR10 without narrowing scope.
- **Original C synchronous refresh not selected:** rafachafa and gamachiel objected to unclear ownership across HTTP disconnects. kings conceded and revised to one application-owned background run with persisted status; no queue service added.
- **Original refresh/cursor/limit vagueness rejected:** All authors accepted the concrete completeness, finite-cursor, run recovery, resource and early evidence-gate corrections in `03-decisions.md`.
- **Over-engineering audit:** Every retained component maps to spec IDs. Standalone auth, external identity, generic policy server, cache, queue/broker, scheduler, distributed services, Delta and frontend remain excluded with revisit triggers in the spec. Container isolation and small local run/cursor records remain because they directly support FR6/FR8/FR10/FR11/TR3/TR6.
