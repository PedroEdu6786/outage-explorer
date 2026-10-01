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
- **FR5:** WHEN valid seeded credentials are submitted THE SYSTEM SHALL authenticate the corresponding Viewer, Analyst, or Admin identity.
- **FR6:** WHEN any data operation is requested THE SYSTEM SHALL enforce the caller's role before retrieving data or executing the query: Viewer may access national analytical datasets only; Analyst and Admin may access all analytical datasets.
- **FR7:** WHEN an authenticated user requests the catalog THE SYSTEM SHALL return only authorized datasets with their columns and types.
- **FR8:** WHEN an authenticated user requests a preview THE SYSTEM SHALL return authorized records with applicable date/facility filters and deterministic backend pagination.
- **FR9:** WHEN a user submits a supported read-only analytical query THE SYSTEM SHALL execute it over authorized product datasets, supporting projections, filters, aggregations, joins, CTEs, subqueries, and window functions without requiring predefined investigations.
- **FR10:** IF a query writes data, changes schema/configuration, accesses unauthorized sources, or has unsupported/unresolvable data access THEN THE SYSTEM SHALL reject it before execution.
- **FR11:** WHEN an Admin requests refresh THE SYSTEM SHALL perform a controlled ingestion and return a clear outcome.
- **FR12:** WHEN a user requests the daily fleet offline-capacity share THE SYSTEM SHALL provide the documented metric using verified source fields and units with explicit missing/zero-denominator handling.
- **FR13:** WHEN the analytical delivery is evaluated THE SYSTEM SHALL provide reproducible reconciliation across all three grains for at least 30 days.
- **FR14:** WHEN the analytical delivery is evaluated THE SYSTEM SHALL provide at least three real EIA anomalies with periods, affected entities where applicable, observed values, product treatment, and reproducible evidence distinguishing observed facts from hypotheses.
- **FR15:** IF a caller without Admin permission requests refresh THEN THE SYSTEM SHALL deny the request before starting ingestion.
- **FR16:** WHEN authorized clients access the deployed backend THE SYSTEM SHALL serve their permitted datasets from the application's common published data without requiring client-side copies or EIA credentials.

### Technical / Non-functional
- **TR1:** Source data is EIA Open Data API v2 daily `us-nuclear-outages`, `facility-nuclear-outages`, and `generator-nuclear-outages`. Raw extracts must be Parquet; modeled data must be Parquet or Delta.
- **TR2:** Authentication is sufficient for a challenge with seeded database users. Secrets remain outside committed code; passwords must not be stored as plaintext. No auth provider or session mechanism is selected.
- **TR3:** SQL is bounded by documented result and execution-resource limits, and all supported dataset references must be authorized before execution. Broad analytical syntax does not grant arbitrary filesystem, network, extension, metadata, or administrative access.
- **TR4:** Local setup, seeded accounts, environment configuration, automated tests, schema/relationships, assumptions, limitations, and decisions must be documented. Incremental history and Engineering Notes must identify AI contributions, a concrete AI mistake caught, and independent verification.
- **TR5:** Natural keys, required fields, types, units, relationships, metric mapping, and source revision behavior must be established from actual EIA metadata/records, not invented.
- **TR6:** Refresh coverage, freshness, concurrent-reader behavior, partial failure, and retention sufficient to reproduce delivered findings must be explicit. [NEEDS CLARIFICATION: Q1 — agree refresh/freshness and evidence-retention behavior after comparing proposals.]
- **TR7:** Development must be reproducible locally and the application must support realistic shared deployment with one active backend replica, as selected by the user. The challenge's local live session is one supported environment, not the sole deployment target. [NEEDS CLARIFICATION: Q2 — choose hosting, durable storage, execution runtime and resource defaults for one backend replica.]
- **TR8:** Amazon S3 is the durable home for raw/modeled Parquet and DuckDB is the analytical SQL engine, as recorded in [ADR-0001](../../adr/0001-s3-parquet-duckdb.md). Backend analytical disk is disposable; remote reads versus temporary staging remains an implementation choice. Necessary operational state must also persist independently of disposable application/query processes or containers, through a separately specified mechanism. A restart/redeployment must not require another EIA ingestion. Backend hosting and infrastructure SLA are not yet selected; one replica does not mean one client or one permitted concurrent request.

## Inputs & Outputs
- Inputs: EIA metadata and daily rows, requested ingestion dates, seeded login credentials, authenticated catalog/preview/SQL/refresh requests.
- Outputs: local raw/modeled data, validation/refresh outcomes, authorized catalog schemas, filtered/paginated previews, bounded query results, daily fleet metric, reconciliation and anomaly evidence.
- Source field mappings and keys: [NEEDS CLARIFICATION: Q3 — investigate actual EIA metadata and records before finalizing the model and metric.]
- SQL language: broad read-only analytical forms in FR9; [NEEDS CLARIFICATION: Q4 — document selected dialect, function surface, and resource limits after the engine/security feasibility comparison.]
- Exact request/response contracts belong to the design; no source column names are assumed here.

## Scope
### In scope
- Connector, local analytical model, backend authentication/authorization, catalog, preview, broad read-only SQL, Admin refresh, metric, findings, and reproducible delivery.
- Seed one user per fixed persona; Analyst/Admin access all analytical datasets, excluding identity/session data and engine internals.
- Shared deployment/development with one active backend replica, Amazon S3 for persistent Parquet and DuckDB for analytical SQL, accessible to users through the authorized API.

### Out of scope (non-goals)
- Frontend is deferred under the user's existing scope; revisit when the user resumes the full challenge UI. This phase is not the full challenge submission.
- Registration, password recovery, role-management screens, and external identity-provider integration; revisit only if real account lifecycle becomes required.
- SQL writes, schema/admin commands, arbitrary files/network sources, and user extensions; revisit only through an explicit change to the read-only product contract.
- Multiple backend replicas and horizontal autoscaling are deferred by the user's current scope; revisit for an explicit availability/capacity requirement. This does not exclude isolated query workers.
- Scheduled refresh, distributed processing, cache, and a separate auth service have no established requirement; revisit only for measured needs or explicit scope changes. Deployment design is in scope; a cloud vendor remains an open choice.
- Outage-type classification and event reconstruction; revisit only after source support and user value are established.

## Assumptions
- Existing product anchor and backend/data-only scope remain confirmed.
- Deadline/engineering budget is not a decision constraint, per user; this does not imply unlimited infrastructure or justify extra components.
- The user selected one backend replica and Amazon S3 + Parquet + DuckDB. Application-owned data serves all authorized users through a realistic shared deployment. Backend hosting, S3 region/configuration, development storage setup and operational-state persistence remain pending Q2; selecting S3 does not select an AWS compute service.
- Broad SQL means the selected dialect's supported analytical forms, not every vendor's syntax or every engine feature. No silent fallback to single-table-only queries is permitted.
- User has no prescribed Analyst investigations. This does not remove FR13/FR14 findings obligations.

## Acceptance Criteria
- [ ] **AC1:** Ingestion retrieves a complete selected period from all three routes across page boundaries. (verifies FR1)
- [ ] **AC2:** Documented validations detect invalid values/keys with visible outcomes; safe reruns do not duplicate keys or corrupt published data. (verifies FR2, FR3)
- [ ] **AC3:** Catalog, previews, metric, and SQL remain usable with EIA unavailable after ingestion. (verifies FR4)
- [ ] **AC4:** All three seeded users authenticate; invalid credentials fail; direct requests cannot bypass role checks. (verifies FR5, FR6)
- [ ] **AC5:** Viewer catalog/preview/SQL/metric paths never expose facility or generator details; Analyst/Admin can retrieve authorized detail. (verifies FR6, FR7, FR8, FR9, FR12)
- [ ] **AC6:** Preview filters and stable page ordering return the expected authorized records; pages continue on their original data version across refresh or fail with explicit documented expiry, without silently mixing versions. (verifies FR8; TR6)
- [ ] **AC7:** Positive analytical queries demonstrate joins, CTEs, nested subqueries, aggregations, and window functions over permitted datasets; returned results match known inputs. (verifies FR9)
- [ ] **AC8:** Unauthorized references, writes, administrative operations, external-access attempts, and unsupported access forms are rejected before execution; limits are observable and enforced. (verifies FR6, FR10; TR3)
- [ ] **AC9:** Only Admin can refresh; success/failure outcomes identify what was published, failures preserve documented availability behavior, and revised/removed/partially retrieved records follow the declared refresh contract. Existing queries finish on their original data version. (verifies FR3, FR4, FR11, FR15; TR6)
- [ ] **AC10:** Metric agrees with verified source fields/units and documented missing/zero handling. (verifies FR12)
- [ ] **AC11:** Reconciliation spans at least 30 days across all grains and findings contain three actual anomalies reproducible from identified inputs and commands, including after a later refresh and ordinary retention cleanup. (verifies FR13, FR14; TR6)
- [ ] **AC12:** A clean development setup reproduces authentication, data access, and findings using documentation; deployment/storage configuration is documented alongside decisions, schema, tests, and Engineering Notes. (verifies FR1–FR16; TR4, TR7)
- [ ] **AC13:** One active backend replica serves separate authorized clients from the same published data under their respective role permissions; replacing/restarting the backend and query containers preserves published data and recoverable operational state without another EIA fetch or overlapping active backend owners. (verifies FR4, FR6, FR16; TR7, TR8)

## Open Clarifications
- [NEEDS CLARIFICATION: Q1 — agree refresh/freshness and evidence-retention behavior after comparing proposals.]
- [NEEDS CLARIFICATION: Q2 — choose hosting, durable storage, execution runtime and resource defaults for one backend replica.]
- [NEEDS CLARIFICATION: Q3 — investigate actual EIA metadata and records before finalizing the model and metric.]
- [NEEDS CLARIFICATION: Q4 — document selected dialect, function surface, and resource limits after the engine/security feasibility comparison.]
