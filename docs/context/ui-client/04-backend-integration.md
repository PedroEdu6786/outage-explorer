# Backend integration contract and gaps

The implemented [HTTP contract](../../specs/data-api/http-contract.md),
[OpenAPI](../../specs/data-api/openapi.json) and
[client handoff](../../specs/data-api/client-handoff.md) describe backend source.
Revalidate availability against the running backend and paired worker image;
source implementation and controlled tests do not establish live readiness.
This repository documents the API; web implementation belongs to its own project.

## Current backend operations

The layered Flask monolith provides opt-in session/authentication, catalog,
preview, SQL execution/retained paging and Admin refresh endpoints. PostgreSQL/RDS
owns operational state, S3 owns three unified resource Parquet files per generation,
and isolated DuckDB workers scan public-column views over exact staged files.
Deployment targets EC2; local development does not require provisioning EC2.
`GET /health` is unauthenticated liveness, never analytical readiness.

| Operation | Implemented contract |
| --- | --- |
| Resolve session | `/api/auth/session`; seeded application role, fixed expiry, session-bound CSRF |
| Login/callback/logout | Flask-owned PKCE and HttpOnly cookie; no provider tokens in browser API |
| Catalog | `/api/datasets`; authorized datasets, schema, coverage and supported filters |
| Preview | `/api/datasets/{dataset}/preview`; initial selection then cursor-only continuation |
| SQL | `/api/query`; one execution and numbered retained pages by query ID |
| Refresh | Admin-only admission/latest/by-ID; background publication, no caller date overrides |

Analyst/Admin may preview Facilities or Generators with one exact `facility` string
and optional inclusive dates. National accepts dates only. Preserve leading zeros
and case; omit a cleared filter rather than sending an empty string. The bound is
1–256 UTF-8 bytes; surrounding whitespace, controls, malformed input and repeated
parameters are rejected.
A valid unmatched identifier yields an empty preview. Follow continuation cursors
without resending filters or page size. Filter changes begin a new sequence.
Catalog `supported_filters` is `["start_date", "end_date"]` for national and
`["start_date", "end_date", "facility"]` for both detail grains. Strict two-date
client decoders must accept the expanded array. There is no discovery endpoint.

The paired execution protocol is version 2. A matching rebuilt/reviewed worker
image and updated matching runtime profile/evidence are required; restarting an
older image or submitting a data refresh cannot add this support. Existing profile
identities are not automatically upgraded. See the
[feature verification](../../specs/preview-facility-filter/verification.md) and
[worker runbook](../../../infrastructure/analytical-worker/README.md).

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

Normalize the implemented error envelopes into feature states while preserving
HTTP status and error codes from the contract. Distinguish unauthenticated,
forbidden, invalid input, unsupported SQL, execution busy, execution timeout,
unavailable data, expired preview, lost/expired query result and service failure.

For SQL, preserve the contracted column order/types, duplicate column labels,
nulls, numeric precision and date encoding. Rows may contain arbitrary
projection/aggregate results and duplicates. A simplistic object keyed solely
by a column name can lose duplicate labels; use rows aligned with ordered columns.

Preserve the separate pagination contracts:

| Property | Dataset preview | SQL result |
| --- | --- | --- |
| Selection | Opaque continuation cursor | Numbered `page` by opaque `query_id` |
| Stability | Original snapshot, filters and ordering | One execution's sequence and multiplicity |
| Size | Default 100; initial configurable maximum 500 | Fixed within execution; default 100 / maximum 500 |
| Expiry | 60 seconds from first page | 60 seconds from execution completion |
| Recovery | Explicit restart of browsing | Explicit rerun, new ID |
| Total output | Backend-paginated browsing | Baseline 1,000 rows or 1 MiB for the entire execution |

Preview and SQL have separate state and pagination even though current size and
lifetime defaults agree. A backend restart can lose
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
