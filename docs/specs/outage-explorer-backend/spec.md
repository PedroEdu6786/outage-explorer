# Spec: Outage Explorer data and backend
> Status: draft · Slug: outage-explorer-backend

## Problem
People exploring U.S. nuclear outages must manually reshape EIA records and reconcile national, facility, and generator observations. They need data available from our deployed backend's own storage, reproducible evidence, and reliable role boundaries while exploring freely. “Local” means ingested and controlled by our application rather than queried live from EIA; it does not mean an individual user's computer.

## Goal
Deliver the challenge's connector, analytical model, and authenticated backend with realistic development/deployment so all authorized users can explore the backend's stored datasets and reproduce actual cross-grain findings.

## Requirements
### Functional (EARS)
- **FR1:** WHEN ingestion is requested THE SYSTEM SHALL retrieve all pages in the requested daily period from the national, facility, and generator EIA nuclear outage routes.
- **FR2:** WHEN records are ingested THE SYSTEM SHALL validate required fields, types, and keys and report invalid records according to a documented policy.
- **FR3:** WHEN ingestion is repeated THE SYSTEM SHALL preserve a valid locally queryable dataset without duplicate natural keys or corrupted published data.
- **FR4:** WHEN upstream EIA is unavailable after successful ingestion THE SYSTEM SHALL serve browsing and analytical queries from local data.
- **FR5:** WHEN a seeded persona completes authentication THE SYSTEM SHALL establish the corresponding Viewer, Analyst, or Admin identity through Amazon Cognito managed login using OAuth2 Authorization Code with PKCE, with the accepted one-hour application session and current-session logout behavior (ADR-0018).
- **FR6:** WHEN any data operation is requested THE SYSTEM SHALL enforce the caller's role before retrieving data or executing the query: Viewer may access national analytical datasets only; Analyst and Admin may access all analytical datasets. Granular RBAC/ABAC and applicable row/column policies must apply consistently across all access paths; our SQLite authorization tables own roles, permissions and policy attributes (ADR-0016); concrete restrictions and enforcement design remain open (ADR-0014).
- **FR7:** WHEN an authenticated user requests the catalog THE SYSTEM SHALL return only authorized datasets with their columns and types.
- **FR8:** WHEN an authenticated user requests a preview THE SYSTEM SHALL return authorized records with applicable date/facility filters and deterministic backend pagination: 100 rows by default, initial configurable maximum 500, and a snapshot-bound cursor expiring 15 minutes after the first page (ADR-0015).
- **FR9:** WHEN a user submits a supported read-only analytical query THE SYSTEM SHALL execute it over authorized product datasets, supporting projections, filters, aggregations, joins, CTEs, subqueries, and window functions without requiring predefined investigations. Target DuckDB analytical feature support broadly; document exclusions only for demonstrated issues (ADR-0012).
- **FR10:** IF a query writes data, changes schema/configuration, accesses unauthorized sources, or has unsupported/unresolvable data access THEN THE SYSTEM SHALL reject it before execution.
- **FR11:** WHEN an Admin requests refresh THE SYSTEM SHALL perform ingestion in the background, expose its outcome, and automatically make the updated data active on successful completion without a separate approval or publish action. See [ADR-0003](../../adr/0003-admin-refresh-publication.md).
- **FR12:** WHEN an authorized user requests the daily fleet offline-capacity share THE SYSTEM SHALL provide a ready-made daily analytical dataset using national same-day `outage / capacity` (multiply by 100 for percent), with both source fields in MW and EIA's `percentOutage` retained for comparison, without requiring the user to derive the formula. Explicit missing/zero/invalid-denominator handling remains to be defined. See [ADR-0006](../../adr/0006-daily-fleet-offline-share.md).
- **FR13:** WHEN the analytical delivery is evaluated THE SYSTEM SHALL provide reproducible reconciliation across all three grains for at least 30 days.
- **FR14:** WHEN the analytical delivery is evaluated THE SYSTEM SHALL provide at least three real EIA anomalies with periods, affected entities where applicable, observed values, product treatment, and reproducible evidence distinguishing observed facts from hypotheses.
- **FR15:** IF a caller without Admin permission requests refresh THEN THE SYSTEM SHALL deny the request before starting ingestion.
- **FR16:** WHEN authorized clients access the deployed backend THE SYSTEM SHALL serve their permitted datasets from the application's common published data without requiring client-side copies or EIA credentials.

### Technical / Non-functional
- **TR1:** Source data is EIA Open Data API v2 daily `us-nuclear-outages`, `facility-nuclear-outages`, and `generator-nuclear-outages`. Raw extracts must be Parquet; modeled data must be Parquet or Delta.
- **TR2:** OAuth2 is required; OIDC is not required (ADR-0017 supersedes the OIDC requirement in ADR-0014). Keep seeded challenge personas and local operational identity records. Amazon Cognito User Pools provides managed login and OAuth2 token issuance via Authorization Code with PKCE (ADR-0018). Exact client configuration and token/session mapping remain open. Our own authorization tables determine application permissions (ADR-0016). Accepted application sessions last one hour by default, with no automatic renewal initially, independent concurrent logins, and current-session invalidation on logout. Secrets remain outside committed code; passwords must not be stored as plaintext. Cognito stores and verifies seeded credentials; the application keeps local identity mappings and permissions. Public registration remains disabled.
- **TR3:** SQL is bounded by documented result and execution-resource limits, and all supported dataset references must be authorized before execution. Accepted in [ADR-0007](../../adr/0007-bounded-parquet-query-execution.md): batch-based Parquet reads without mandatory full-dataset materialization, bounded memory and temporary disk, limited query concurrency, bounded result fetching, and query failure isolated from API availability. Accepted starting controls in [ADR-0013](../../adr/0013-initial-query-controls.md): one isolated analytical worker at a time, retryable busy responses, a 10-second execution deadline, and results capped at 1,000 rows or 1 MiB with explicit truncation. Worker/DuckDB memory sizes, separate disk quotas and preparation/overall deadline remain to be measured. Broad analytical syntax does not grant arbitrary filesystem, network, extension, metadata, or administrative access.
- **TR4:** Local setup, seeded accounts, environment configuration, automated tests, schema/relationships, assumptions, limitations, and decisions must be documented. Incremental history and Engineering Notes must identify AI contributions, a concrete AI mistake caught, and independent verification.
- **TR5:** Natural keys, required fields, types, units, relationships, metric mapping, and source revision behavior must be established from actual EIA metadata/records, not invented.
- **TR6:** Refresh coverage, freshness, concurrent-reader behavior and partial failure must be explicit. Use recent dates covering at least 30 days for reconciliation (ADR-0009); preserve findings inputs. Snapshot retention/recovery policy and automated deletion are deferred (ADR-0010). Admin-triggered background refresh and automatic publication on success are accepted in ADR-0003. [NEEDS CLARIFICATION: Q1 — verify the recent interval and source-completeness rules; retention policy is deferred.]
- **TR7:** Development must be reproducible locally and the application must support realistic shared deployment with one active backend replica, as selected by the user. The challenge's local live session is one supported environment, not the sole deployment target. [NEEDS CLARIFICATION: Q2 — finalize ECS launch type, durable SQLite storage, execution runtime and resource defaults for one backend replica.]
- **TR8:** Amazon S3 is the durable home for raw/modeled Parquet and DuckDB is the analytical SQL engine, as recorded in [ADR-0001](../../adr/0001-s3-parquet-duckdb.md). Backend analytical disk is disposable; [ADR-0008](../../adr/0008-local-parquet-file-cache.md) selects a bounded local disk cache of immutable modeled Parquet, scanned by workers with only authorized files and no network or S3 credentials. Necessary operational state must also persist independently of disposable application/query processes or containers, through a separately specified mechanism. A restart/redeployment must not require another EIA ingestion. Amazon ECS is selected (ADR-0011); launch type, durable SQLite mechanism and infrastructure SLA are not yet selected; one replica does not mean one client or one permitted concurrent request.

## Inputs & Outputs
- Accepted stack: Python/FastAPI ([ADR-0004](../../adr/0004-python-fastapi-backend.md)), SQLite operational storage and AWS hosting ([ADR-0005](../../adr/0005-sqlite-on-aws.md)); ECS is selected in [ADR-0011](../../adr/0011-ecs-hosting.md); launch type and durable SQLite storage mechanism remain open.
- Modeling approach: EIA observations use analytical datasets with versioned schema contracts, accepted in [ADR-0002](../../adr/0002-analytical-dataset-contracts.md). Operational entities retain separate persistence; exact analytical fields and keys remain subject to TR5/Q3.
- Inputs: EIA metadata and daily rows, requested ingestion dates, seeded login credentials, authenticated catalog/preview/SQL/refresh requests.
- Outputs: local raw/modeled data, validation/refresh outcomes, authorized catalog schemas, filtered/paginated previews, bounded query results, daily fleet metric, reconciliation and anomaly evidence.
- Source field mappings and keys: Q3 is partially resolved by [ADR-0006](../../adr/0006-daily-fleet-offline-share.md): national metric fields, units and three-date formula agreement are verified. Other dataset keys/mappings, detailed capacity semantics, edge-case policy and broader reconciliation remain open.
- SQL language: DuckDB read-only analytical features under [ADR-0012](../../adr/0012-duckdb-analytical-feature-scope.md), with appropriate unsupported-query errors and exclusions justified by demonstrated issues. [NEEDS CLARIFICATION: Q4 — verify compatibility, reference authorization and resource limits on pinned versions.]
- Exact request/response contracts belong to the design; no source column names are assumed here.

## Scope
### In scope
- Connector, local analytical model, backend authentication/authorization, catalog, preview, broad read-only SQL, Admin refresh, metric, findings, and reproducible delivery.
- Seed one user per fixed persona; Analyst/Admin access all analytical datasets, excluding identity/session data and engine internals.
- Shared deployment/development with one active backend replica, Amazon S3 for persistent Parquet and DuckDB for analytical SQL, accessible to users through the authorized API.

### Out of scope (non-goals)
- Candidate review, Admin validation/approval workflows and a separate publish action for refreshed data are excluded from the current scope (ADR-0003).
- Frontend is deferred under the user's existing scope; revisit when the user resumes the full challenge UI. This phase is not the full challenge submission.
- Registration, password recovery and role-management screens remain excluded. OAuth2 remains in scope; OIDC integration is not required under ADR-0017.
- SQL writes, schema/admin commands, arbitrary files/network sources, and user extensions; revisit only through an explicit change to the read-only product contract.
- Multiple backend replicas and horizontal autoscaling are deferred by the user's current scope; revisit for an explicit availability/capacity requirement. This does not exclude isolated query workers.
- Scheduled refresh, distributed processing, query-result caching and a custom-built authorization server have no established requirement; revisit only for measured needs or explicit scope changes. Deployment design is in scope; Amazon ECS is selected; its launch/storage pattern remains to be finalized.
- Outage-type classification and event reconstruction; revisit only after source support and user value are established.

## Assumptions
- Existing product anchor and backend/data-only scope remain confirmed.
- Deadline/engineering budget is not a decision constraint, per user; this does not imply unlimited infrastructure or justify extra components.
- The user selected one backend replica and Amazon S3 + Parquet + DuckDB. Application-owned data serves all authorized users through a realistic shared deployment. ECS hosting is selected. ECS launch type, S3 region/configuration, development storage setup and operational-state persistence remain pending Q2. Snapshot retention/recovery-policy work is deferred.
- Broad SQL means the selected dialect's supported analytical forms, not every vendor's syntax or every engine feature. No silent fallback to single-table-only queries is permitted.
- User has no prescribed Analyst investigations. This does not remove FR13/FR14 findings obligations.

## Acceptance Criteria
- [ ] **AC1:** Ingestion retrieves a complete selected period from all three routes across page boundaries. (verifies FR1)
- [ ] **AC2:** Documented validations detect invalid values/keys with visible outcomes; safe reruns do not duplicate keys or corrupt published data. (verifies FR2, FR3)
- [ ] **AC3:** Catalog, previews, metric, and SQL remain usable with EIA unavailable after ingestion. (verifies FR4)
- [ ] **AC4:** All three seeded personas authenticate through Cognito managed login and the selected OAuth2 flow; invalid/expired/revoked sessions fail, current-session logout stops access, and direct requests cannot bypass role or configured granular policies. Verify trusted local-user binding and correct access-token validation under the selected OAuth2 design. (verifies FR5, FR6)
- [ ] **AC5:** Viewer catalog/preview/SQL/metric paths never expose facility or generator details; Analyst/Admin can retrieve authorized detail. (verifies FR6, FR7, FR8, FR9, FR12)
- [ ] **AC6:** Preview filters and stable page ordering return the expected authorized records; pages continue on their original data version across refresh or fail with explicit documented expiry, without silently mixing versions. (verifies FR8; TR6)
- [ ] **AC7:** Positive analytical queries demonstrate joins, CTEs, nested subqueries, aggregations, and window functions over permitted datasets; returned results match known inputs. (verifies FR9)
- [ ] **AC8:** Unauthorized references, writes, administrative operations, external-access attempts, and unsupported access forms are rejected before execution; limits are observable and enforced. (verifies FR6, FR10; TR3)
- [ ] **AC9:** Only Admin can refresh; the background run exposes its outcome and successful completion activates the updated data without another Admin action. Previous published data remains available during refresh and after failure; revised/removed/partially retrieved records follow the declared refresh contract. Existing queries finish on their original data version. (verifies FR3, FR4, FR11, FR15; TR6)
- [ ] **AC10:** Metric agrees with verified source fields/units and documented missing/zero handling. (verifies FR12)
- [ ] **AC11:** Reconciliation spans at least 30 days across all grains and findings contain three actual anomalies reproducible from identified inputs and commands, including after a later refresh and local cache eviction. (verifies FR13, FR14; TR6)
- [ ] **AC12:** A clean development setup reproduces authentication, data access, and findings using documentation; deployment/storage configuration is documented alongside decisions, schema, tests, and Engineering Notes. (verifies FR1–FR16; TR4, TR7)
- [ ] **AC13:** One active backend replica serves separate authorized clients from the same published data under their respective role permissions; replacing/restarting the backend and query containers preserves published data and recoverable operational state without another EIA fetch or overlapping active backend owners. (verifies FR4, FR6, FR16; TR7, TR8)

## Open Clarifications
- **Q3 discussion timing:** user deferred validation and publication-policy decisions until source inspection establishes clearer data models. No proposed missing-value, duplicate or reject-versus-exclude policy is accepted by this deferral.
- [NEEDS CLARIFICATION: Q1 — verify the recent interval and source-completeness rules; retention policy is deferred; background refresh with automatic publication is accepted in ADR-0003.]
- [NEEDS CLARIFICATION: Q2 — finalize ECS launch type, durable SQLite storage, execution runtime and resource defaults for one backend replica.]
- [NEEDS CLARIFICATION: Q3 — partially resolved; complete source keys/relationships, detailed capacity semantics, missing/zero/invalid-input policy, comparison tolerance, historical checks and cross-grain reconciliation. See ADR-0006 for verified national metric evidence.]
- [NEEDS CLARIFICATION: Q4 — verify broad DuckDB analytical compatibility, reference authorization and resource limits; record demonstrated exclusions.]

- [NEEDS CLARIFICATION: Q5 — finalize Cognito app-client/callback configuration and seeded provisioning, token/session validation and logout mapping, and concrete row/column or attribute-based restrictions. Authentication experience and preview defaults are accepted in ADR-0014/0015, with OAuth2-only protocol scope refined in ADR-0017 and Cognito selected in ADR-0018.]
