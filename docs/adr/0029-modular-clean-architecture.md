# ADR-0029: Organize the backend as a modular monolith with ports and adapters

Status: **Proposed**

Date: 2026-10-01

## Context

The product combines authorized analytical queries, asynchronous refresh,
versioned datasets, and reproducible evidence. These behaviors must share
business rules across Flask routes, jobs, and verification commands. Existing
choices include one backend replica, SQLite, S3, Parquet, DuckDB, and Cognito.

## Options considered

1. A layered Flask application offers a small initial structure but can couple
   application policies to concrete storage and request context.
2. A modular monolith with Clean Architecture dependency rules gives each
   capability explicit ownership and keeps integrations outside use cases.
3. Independently deployed API, ingestion, and query services support separate
   scaling but introduce coordination and network contracts without a current
   requirement for independent deployment.

## Proposed decision

Choose option 2. Use `access`, `datasets`, `exploration`, and `refresh` modules.
Domain policies remain pure Python; application services own orchestration and
authorization. Ports describe external capabilities; adapters implement them.
A composition root supplies dependencies. Flask handles HTTP only.

Keep analytical workers isolated and refresh independently supervised within
one product and release. Process isolation does not require microservices.
Use direct application calls, small interfaces, and bounded batch processing.
No message bus, event sourcing, generic repository hierarchy, or new broker
is justified by the current requirements.

## Consequences and acceptance boundary

The structure enables policy tests without HTTP/cloud context and explicit
storage/execution ownership, at the cost of maintaining interfaces and import
rules. Acceptance requires meaningful unit, adapter, sandbox, concurrency,
and crash-recovery tests; folder organization alone proves nothing.

The proposed one-process WSGI state owner and supervised refresh lifecycle
require measurement and replacement tests. ECS launch type, durable SQLite
volume lifecycle, SQL sandbox launcher, session mapping, source contracts,
and resource budgets remain open. They are not selected by this ADR.

See the [full comparison and design](../specs/outage-explorer-backend/architecture-options.md)
for dependency diagrams, module responsibilities, flows, evidence, and sources.
