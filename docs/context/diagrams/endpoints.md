# API endpoints: high-level responsibilities

Flask routes validate transport inputs and call injected application services.
Application use cases enforce current local roles before protected work.
Cognito supplies identity; PostgreSQL owns local users, roles and sessions.

```mermaid
flowchart TD
    Client["Web client or API caller"] --> Routes["Thin Flask routes<br/>Input validation, cookies, Origin and CSRF<br/>Bounded responses and safe errors"]
    Routes --> Public["Health and API documentation<br/>No protected analytical reads"]
    Routes --> Login["Login and callback use cases"]
    Cognito["Cognito managed authentication"] <--> Login
    Login --> AuthState["PostgreSQL<br/>Users, roles, login attempts, sessions"]
    Routes --> Access["Current session and role checks<br/>Enforced by application use cases"]
    AuthState --> Access
    Access --> Session["Session details and current-session logout"]
    Access --> Catalog["Authorized dataset catalog<br/>Public schemas and published coverage"]
    Access --> Preview["Dataset preview<br/>Authorize grain, bind snapshot<br/>and retain cursor sequence"]
    Access --> SQL["SQL use case"]
    SQL --> Parser["Bounded parser subprocess<br/>Inspect all references and functions"]
    Parser --> SQLAuth["Authorize complete inspected scope<br/>before analytical input access"]
    Preview --> Inputs["Trusted resource cache<br/>Verify and pin exact authorized files"]
    SQLAuth -->|"Referenced datasets"| Inputs
    SQLAuth -->|"Reference-free expression"| Engine
    S3["S3<br/>Three immutable resource files per generation"] --> Inputs
    Publication["PostgreSQL<br/>Exact publication descriptors and active pointer"] --> Catalog
    Publication --> Inputs
    Inputs --> Engine["Isolated DuckDB worker<br/>Public-only views, no credentials/network<br/>Bounded resources and confirmed termination"]
    Engine -->|"Preview"| PreviewResult["Bounded preview page<br/>Snapshot-bound cursor"]
    Engine -->|"SQL"| SQLResult["Retain one SQL execution's output<br/>Owned query ID and fixed expiry"]
    Access --> Pages["SQL continuation<br/>Recheck owner and current permissions<br/>Read retained output without rerunning SQL"]
    SQLResult --> Pages
    Access --> Refresh["Admin refresh use cases<br/>Admit run or read durable status"]
    Refresh --> Coordination["PostgreSQL<br/>Frozen interval, idempotency and run ownership"]
    Coordination -.-> Worker["Independent refresh worker<br/>Connector and verified publication flow"]
```

The branches share authorization policy, not a route-owned authorization engine.
Preview pages can perform bounded worker reads on their pinned snapshot. SQL
continuation pages read a retained execution and never execute SQL again.
Catalog uses application definitions and PostgreSQL metadata, without downloading
analytical files. Reference-free SQL skips generation/file preparation after
inspection and authorization; it still uses isolated execution and result bounds.
Only the trusted loader accesses S3; analytical/parser workers receive no cloud
or operational-database credentials. Refresh runs outside the HTTP lifecycle.

| Capability | HTTP operations |
| --- | --- |
| Health / documentation | `GET /health`, `GET /api/docs`, `GET /api/openapi.json` |
| Authentication / session | `GET /api/auth/login`, `GET /api/auth/callback`, `GET /api/auth/session`, `POST /api/auth/logout` |
| Catalog / preview | `GET /api/datasets`, `GET /api/datasets/{dataset}/preview` |
| SQL execute / retained pages | `POST /api/query`, `GET /api/query` |
| Admin refresh / status | `POST /api/refresh`, `GET /api/refresh/latest`, `GET /api/refresh/{run_id}` |

Viewer accesses national data; Analyst/Admin access all three grains; refresh and
its protected diagnostics require Admin. Transport enablement and reviewed
analytical startup remain explicit composition steps. This diagram does not
claim fresh live persona, isolation or deployment acceptance.

Sources: [HTTP routes](../../../src/outage_explorer/entrypoints/http/routes/),
[application services](../../../src/outage_explorer/application/services/),
[data HTTP contract](../../specs/data-api/http-contract.md),
[auth HTTP contract](../../specs/user-access/http-contract.md).

[All module diagrams](../module-diagrams.md) · [Decisions](../../../DECISIONS.md)
