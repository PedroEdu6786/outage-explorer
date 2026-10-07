# API endpoints: individual flow diagrams

Each HTTP operation has its own high-level diagram below. Flask handles transport;
application services enforce current identity and role before protected work.
Reviewed against current workspace source on October 7, 2026. These diagrams
explain responsibilities, not fresh live acceptance or deployment.

Common behavior: protected errors omit secrets and unauthorized schema details;
configured transport applies credentialed CORS, exact Origin/CSRF rules for
mutations and no-store responses. OPTIONS preflight is shared transport behavior,
not a separate product use case. Concrete services are injected at startup;
imports and app factories start no jobs. Optional services still require explicit
configuration/analytical startup. Invalid inputs and failed dependencies return
safe errors rather than continuing along the successful paths shown.

| HTTP operation | Diagram |
| --- | --- |
| `GET /health` | [Health](#health) |
| `GET /api/docs` | [API documentation](#api-documentation) |
| `GET /api/openapi.json` | [OpenAPI contract](#openapi-contract) |
| `GET /api/auth/login` | [Begin login](#begin-login) |
| `GET /api/auth/callback` | [Complete login](#complete-login) |
| `GET /api/auth/session` | [Current session](#current-session) |
| `POST /api/auth/logout` | [Logout](#logout) |
| `GET /api/datasets` | [Dataset catalog](#dataset-catalog) |
| `GET /api/datasets/{dataset}/preview` | [Dataset preview](#dataset-preview) |
| `POST /api/query` | [Execute SQL](#execute-sql) |
| `GET /api/query` | [Read SQL result page](#read-sql-result-page) |
| `POST /api/refresh` | [Admit refresh](#admit-refresh) |
| `GET /api/refresh/latest` | [Latest refresh](#latest-refresh) |
| `GET /api/refresh/{run_id}` | [Refresh status](#refresh-status) |

## Health

`GET /health`

```mermaid
flowchart TD
    Request["GET /health"] --> Check["HealthService.check<br/>Read clock and scaffold liveness"]
    Check --> Response["200 JSON<br/>status, service, checked_at"]
```

Public liveness only. Does not query PostgreSQL, Cognito, S3 or DuckDB and does not establish readiness.

## API documentation

`GET /api/docs`

```mermaid
flowchart TD
    Request["GET /api/docs"] --> UI["Serve packaged Swagger UI assets"]
    UI --> Browser["Browser loads API documentation"]
    Browser --> Contract["Fetch GET /api/openapi.json"]
```

Public documentation. Trying protected operations still requires their normal authentication, authorization and configured resources.

## OpenAPI contract

`GET /api/openapi.json`

```mermaid
flowchart TD
    Request["GET /api/openapi.json"] --> File["Read packaged OpenAPI contract"]
    File --> Mode["Apply configured development cookie names<br/>when development HTTP is selected"]
    Mode --> Response["200 OpenAPI JSON<br/>Cache-Control: no-store"]
```

Public contract metadata; serving the contract starts no connector or analytical worker.

## Begin login

`GET /api/auth/login`

```mermaid
flowchart TD
    Request["GET /api/auth/login<br/>Optional allowed return_to"] --> Validate["Validate requested return destination"]
    Validate --> Material["Generate state, browser binding<br/>and PKCE verifier/challenge"]
    Material --> Store["PostgreSQL<br/>Store bounded single-use login attempt"]
    Store --> Response["302 to Cognito authorization URL<br/>Set browser-binding attempt cookie"]
    Response --> Cognito["Browser opens managed login"]
```

Login establishes an attempt, not an application session. Invalid destinations are rejected before creating it.

## Complete login

`GET /api/auth/callback`

```mermaid
flowchart TD
    Request["GET /api/auth/callback<br/>code, state and browser-binding cookie"] --> Attempt["Atomically consume matching<br/>unexpired login attempt in PostgreSQL"]
    Attempt --> Provider["Cognito adapter<br/>Exchange code with PKCE and verify identity"]
    Provider --> User["Resolve seeded local issuer/subject<br/>Require a valid application role"]
    User --> Session["Create fixed-expiry application session<br/>Store token digest in PostgreSQL"]
    Session --> Response["302 to allowed frontend destination<br/>Set session cookie, clear attempt cookie"]
```

No local session is created for invalid/replayed attempts or an unlinked identity. Callback failures also clear the attempt cookie; provider work is outside the attempt-consumption transaction.

## Current session

`GET /api/auth/session`

```mermaid
flowchart TD
    Request["GET /api/auth/session<br/>Application session cookie"] --> Resolve["Resolve token digest in PostgreSQL<br/>Check expiry/revocation and current local role"]
    Resolve --> Identity["Build current identity<br/>and session-bound CSRF token"]
    Identity --> Response["200 JSON<br/>User identity, role, fixed expiry, csrf_token"]
```

Unauthenticated or expired sessions fail. Reading the session does not renew its expiry or access analytical data.

## Logout

`POST /api/auth/logout`

```mermaid
flowchart TD
    Request["POST /api/auth/logout"] --> Transport["Validate exact Origin<br/>and logout session/CSRF policy"]
    Transport --> Valid{"Valid current session<br/>and CSRF?"}
    Valid -->|"Yes"| Revoke["PostgreSQL<br/>Revoke this session digest"]
    Valid -->|"Missing or invalid session<br/>accepted by logout policy"| Clear["Clear application session cookie"]
    Revoke --> Clear
    Clear --> Response["204 No Content"]
```

Invalid Origin or invalid CSRF on a valid session is rejected. Logout invalidates only the current application session; Cognito browser logout is a separate client flow.

## Dataset catalog

`GET /api/datasets`

```mermaid
flowchart TD
    Request["GET /api/datasets"] --> Access["Resolve current session and local role<br/>Authorize the permitted grain set"]
    Access --> Definitions["Select public dataset definitions<br/>Viewer: national; Analyst/Admin: all grains"]
    Definitions --> Publication["PostgreSQL<br/>Read active resource generation and coverage"]
    Publication --> Ready{"Published generation<br/>available?"}
    Ready -->|"Yes"| Response["200 JSON<br/>Authorized schemas, coverage and generation_id"]
    Ready -->|"No"| Unavailable["Data unavailable response"]
```

No S3 download or DuckDB execution. The payload exposes only public columns and authorized datasets.

## Dataset preview

`GET /api/datasets/{dataset}/preview`

```mermaid
flowchart TD
    Request["GET dataset preview<br/>Optional dates/page_size OR cursor"] --> Access["Resolve session and authorize requested grain<br/>Validate filters or cursor-only continuation"]
    Access --> Kind{"Cursor supplied?"}
    Kind -->|"Yes"| Existing["Acquire owned unexpired sequence<br/>Use its original snapshot, files and position"]
    Kind -->|"No"| Initial["Reserve analytical slot<br/>Read active generation from PostgreSQL"]
    Initial --> Inputs["Trusted cache: verify/pin resource file<br/>Download exact S3 object only on cache miss<br/>Create owned snapshot-bound sequence"]
    Inputs --> Worker["Isolated DuckDB preview<br/>Public projection, filters and stable keyset order"]
    Existing --> Slot["Reserve analytical slot"]
    Slot --> Worker
    Worker --> Close["Validate and encode bounded page<br/>Confirm worker termination and release active lease"]
    Close --> Response["200 JSON<br/>Rows, schema, generation_id, cursors and expiry"]
```

Both first-page and cursor requests recheck current permissions. Continuations do not switch generations. Unknown/forbidden datasets have safe errors; expiry/loss requires an explicit restart. The sequence retains its file pins until expiry/discard.

## Execute SQL

`POST /api/query`

```mermaid
flowchart TD
    Request["POST /api/query<br/>Body: sql; query: page/page_size"] --> Transport["Validate Origin, session-bound CSRF<br/>and submission parameters"]
    Transport --> Inspect["Resolve identity<br/>Bounded parser subprocess inspects complete SQL"]
    Inspect --> Access["Application authorizes all referenced grains<br/>Reject unsafe or unresolved access"]
    Access --> Reserve["Reserve retained-result capacity<br/>and single analytical execution slot"]
    Reserve --> Referenced{"References product<br/>datasets?"}
    Referenced -->|"Yes"| Inputs["Resolve active generation<br/>Trusted cache verifies/pins only authorized resources"]
    Referenced -->|"No"| Worker["Isolated DuckDB execution<br/>Submitted SQL unchanged; bounded output"]
    Inputs --> Worker
    Worker --> Retain["Confirm worker termination, release input pins<br/>Retain output once with owner, scope and fixed expiry"]
    Retain --> Page["Recheck owner/current permissions<br/>Read requested retained page"]
    Page --> Response["200 JSON<br/>query_id, columns, rows, limits and truncation"]
```

Invalid SQL, denied references, busy execution and exhausted bounds return explicit errors. Reference-free expressions have null generation identity. No pagination clauses are injected.

## Read SQL result page

`GET /api/query`

```mermaid
flowchart TD
    Request["GET /api/query<br/>query_id, page, optional matching page_size"] --> Identity["Resolve current application session"]
    Identity --> Result["Acquire owned retained result<br/>Check availability and original expiry"]
    Result --> Access["Reauthorize its complete original grain set<br/>Validate fixed page size and requested page"]
    Access --> Read["Read bounded retained output page<br/>No parser, S3 preparation or DuckDB execution"]
    Read --> Response["200 JSON<br/>Same query_id and retained execution metadata"]
```

Foreign, expired or lost results return unavailable errors; invalid page/size requests are rejected. Neither GET nor expiry recovery silently reruns SQL.

## Admit refresh

`POST /api/refresh`

```mermaid
flowchart TD
    Request["POST /api/refresh<br/>Empty body and Idempotency-Key"] --> Transport["Validate Origin and session-bound CSRF"]
    Transport --> Access["Application authorizes current Admin<br/>Validate empty body and idempotency key"]
    Access --> Replay{"Existing matching<br/>admission?"}
    Replay -->|"Yes"| Existing["Return existing durable run"]
    Replay -->|"No"| Admit["Resolve/freeze configured inclusive interval<br/>PostgreSQL admits one owned run and baseline"]
    Existing --> Receipt["202 for nonterminal run; 200 for terminal replay<br/>run_id, effective interval, status URL"]
    Admit --> Receipt
    Admit -.-> Worker["Independent worker later claims the run<br/>Connector, verification and fenced publication"]
```

Admission performs no EIA retrieval or S3 upload. Dates/datasets cannot be overridden by the caller. The worker is independently supervised; browser/API lifetimes do not own it.

## Latest refresh

`GET /api/refresh/latest`

```mermaid
flowchart TD
    Request["GET /api/refresh/latest"] --> Access["Application checks current session<br/>and Admin outcome permission"]
    Access --> Store["PostgreSQL<br/>Read latest durable refresh run"]
    Store --> Response["200 JSON<br/>run payload or run: null"]
```

Status lookup starts no refresh and grants no permission to retry or publish. Database unavailability produces a safe unavailable response.

## Refresh status

`GET /api/refresh/{run_id}`

```mermaid
flowchart TD
    Request["GET /api/refresh/run_id"] --> Validate["Validate transport run identifier"]
    Validate --> Access["Application checks current session<br/>and Admin outcome permission"]
    Access --> Store["PostgreSQL<br/>Read durable run by ID"]
    Store --> Found{"Run exists?"}
    Found -->|"Yes"| Response["200 JSON<br/>Progress, publication outcome and quality summary"]
    Found -->|"No"| Missing["404 refresh_unavailable"]
```

Only Admin can inspect outcomes, even when the ID is known. Polling reads recorded state; it does not run source work or infer publication from an S3 receipt.

## Sources

- [HTTP routes](../../../src/outage_explorer/entrypoints/http/routes/)
- [Application services](../../../src/outage_explorer/application/services/)
- [Data HTTP contract](../../specs/data-api/http-contract.md)
- [Authentication HTTP contract](../../specs/user-access/http-contract.md)
- [Connector and publication flow](data-connector.md)

[All module diagrams](../module-diagrams.md) · [Decisions](../../../DECISIONS.md)
