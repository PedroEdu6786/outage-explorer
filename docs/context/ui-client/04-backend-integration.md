# Backend integration contract and gaps

The current [data API requirements](../../specs/data-api/requirements.md) and
[proposed HTTP contract](../../specs/data-api/http-contract.md) capture the
subsequent endpoint discussion. Shared `/api/query` pagination, configured
all-grain background refresh, date-only initial browsing, and SQL page size/
lifetime are user-selected there. Earlier open items below are historical
integration notes; the new draft takes precedence where they differ.

The UI consumes the Outage Explorer backend. This document captures required
semantics, not a complete OpenAPI specification. Revalidate availability against
the backend version used for integration.

## Verified implementation status on October 4 2026

The Flask application always registers `GET /health`. It returns
`status`, `service` and `checked_at` and sets `Cache-Control: no-store`.
It is unauthenticated liveness; it does not prove data, auth or SQL readiness.

Offline verification for all three grains, connector modeling, local Parquet
verification and EIA adapter work exist. Those are not product HTTP APIs.
User-access Phase 4 now registers opt-in login/callback/session/logout routes,
with controlled HTTP/startup/architecture verification. See the
[authentication contract](../../specs/user-access/http-contract.md). Transport
choices remain draft in ADR-0046/0047; live Cognito and browser reopening checks
remain Phase 5. Authorized catalog/preview/metrics, SQL execution/pagination and
Admin refresh HTTP integration are pending. Cognito and RDS setup were
user-confirmed, but end-to-end application integration is not thereby verified.

The backend stack is a layered Flask monolith, PostgreSQL on RDS for operational
state, S3/Parquet for durable analytical data, and isolated DuckDB execution
against backend-cached authorized inputs. Deployment targets one backend
replica on EC2. Local UI development does not require provisioning EC2.

## Logical operations to agree with the backend

These names identify adapter responsibilities only. They are not endpoint paths
or finalized method/type declarations.

| Operation | Semantics/information needed | Still open |
| --- | --- | --- |
| Resolve session | Current identity, assigned role, fixed expiry and session-bound CSRF | Implemented `/api/auth/session`; live/browser readiness pending |
| Login/callback/logout | Flask-owned PKCE, opaque cookie, current-session invalidation | Implemented auth contract; concrete provider/URL readiness pending |
| List datasets/schema | Only permitted datasets, columns/types and applicable filters/coverage | Dataset IDs/SQL names, routes and payloads |
| Preview records | Dataset and filters; bounded rows, ordering, snapshot and opaque continuation cursor | Request/response schema, cursor transport, previous-page navigation |
| Read fleet metric | National date, source MW and reported/calculated percentages with precision | Catalog dataset versus dedicated route; encoding |
| Execute SQL | SQL, positive `page`/`page_size`; columns, rows, query ID, snapshot and truncation information | Route, response encoding, sync/async delivery and SQL page limits |
| Read query page | `query_id`, requested page and same effective page size; same execution | Route, TTL, out-of-range/error representation |
| Start/check refresh | Admin-only background run, outcome, publication and quality accounting | Routes, status schema and polling mechanism; UI inclusion |

Do not copy proposed `/api/...` paths from an earlier design and treat them as
implemented. Likewise, `fleet_offline_share_daily` is a proposed prepared SQL
dataset name; obtain stable names from the agreed catalog contract.

## Authentication integration boundary

Cognito User Pools managed login and Authorization Code with PKCE are selected.
Seeded accounts are sufficient and public registration is disabled. Application
permissions belong to PostgreSQL, and the backend must enforce them on every
operation, including subsequent preview/result pages.

The implemented draft contract uses browser-to-Flask calls: Flask owns PKCE
exchange/callback and opaque persistent HttpOnly cookies. Use a same-origin proxy
for local UI development, or explicitly configure a same-site UI origin and send
credentialed fetch requests. Read `/api/auth/session` for role, original expiry
and CSRF; send `X-CSRF-Token` and the exact configured Origin on logout. The
[HTTP contract](../../specs/user-access/http-contract.md) records routes, cookies,
errors and environment inputs. Cross-site origins cannot bypass SameSite=Lax
through CORS alone; use a same-origin proxy or revisit the draft transport choice.

Do not introduce a Next.js token bridge, bearer/ID-token API alternative,
localStorage credentials or automatic renewal. Provider tokens never enter the
browser API contract. No backend/AWS secrets may enter client bundles or public
environment variables. ADR-0046/0047 retain proposed status; implementation tests
are not live-provider or browser-readiness evidence.

ADR-0045 keeps a fixed one-hour application session with no automatic renewal.
Browser reopening within a valid session preserves sign-in; special recovery
across backend restarts/outages is outside scope. The application session,
provider token lifetime and Cognito SSO session are different concepts. Sign-out must invalidate the current application session
on the backend; clearing client state alone is not completion. Unknown or
unassigned identities receive no product permissions.

## Error and pagination semantics

Normalize backend failures into feature states without fabricating HTTP status
codes or error identifiers before the contract exists. Distinguish unauthenticated,
forbidden, invalid input, unsupported SQL, execution busy, execution timeout,
unavailable data, expired preview, lost/expired query result and service failure.

For SQL, include column order/types, duplicate column-label handling, nulls,
numeric precision and date encoding in the contract. Rows may contain arbitrary
projection/aggregate results and duplicates. A simplistic object keyed solely
by a column name can lose duplicate labels; agree an unambiguous representation.

Preserve the separate pagination contracts:

| Property | Dataset preview | SQL result |
| --- | --- | --- |
| Selection | Opaque continuation cursor | Numbered `page` by opaque `query_id` |
| Stability | Original snapshot, filters and ordering | One execution's sequence and multiplicity |
| Size | Default 100; initial configurable maximum 500 | Fixed within execution; default/maximum open |
| Expiry | 15 minutes from first page | Fixed lifetime required; numeric TTL open |
| Recovery | Explicit restart of browsing | Explicit rerun, new ID |
| Total output | Backend-paginated browsing | Baseline 1,000 rows or 1 MiB for the entire execution |

Do not reuse preview defaults/expiry as SQL settings. A backend restart can lose
SQL pagination metadata. Cache keys and UI state must distinguish a page of the
same execution from a newly submitted query, even when the SQL text is identical.

## Independent development before API availability

Define a narrow adapter seam and implement explicit fixture responses for
screen and state development. Keep proposed transport contracts labeled as
proposed; fixtures establish UI behavior, not backend compliance. Use the same
feature-facing seam for fixture and eventual HTTP adapters so components need
not know which supplies data.

Make fixture mode explicit in development configuration and visible in demos.
Production configuration must never silently fall back to fixtures after a
backend failure. Fixtures should cover each role, empty results, errors,
expiry, truncation, duplicate SQL rows/labels and stale-request races.

Synthetic observations must be labeled synthetic. If real EIA fixtures are
used, include provenance and preserve their access restrictions. Keep fixture
data out of production client bundles, especially facility/generator examples
that could be downloaded by a Viewer even when their screen is hidden.
