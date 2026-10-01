# Outage Explorer — Problem Anchor

## The Main Problem
Users need to explore U.S. nuclear outage data stored in our backend infrastructure, query datasets their role permits, and understand discrepancies across national, facility, and generator observations using reproducible evidence. All authorized clients use the shared backend; “local” refers to application-owned ingestion, not client-owned files.

## Context
The repository contains project context and devlog tooling, but no application implementation or canonical spec/plan. This is an individual technical challenge. The user asked to discuss fundamentals, tools, implications, and open questions. Prior product decisions were revalidated against current repository context and Engram. The main problem was already explicitly confirmed; the council did not ask for redundant confirmation.

## Known constraints
- Connector, data model, and backend are active; frontend remains deferred.
- Seeded database accounts for Viewer, Analyst, Admin suffice.
- User confirmed broad read-only analytical SQL, including joins, CTEs, subqueries, aggregations, and windows, over authorized datasets.
- No predetermined Analyst investigations; required reconciliation and actual anomaly findings remain.
- User does not want deadline or engineering time to drive this discussion.
- Raw Parquet, modeled Parquet/Delta, real EIA evidence, and non-bypassable authorization are requirements.
- Actual EIA records have not been examined during this council; model facts remain unverified.
- User corrected the laptop-only assumption and then selected one backend replica: realistic development and shared deployment are required. Analytical and operational state must survive process/container replacement; hosting/storage/runtime remain open. Multiple replicas are deferred.

## Out of scope (declared up front)
- Frontend, account-management product, arbitrary engine commands, implementation code, file-level tasks, commits, publishing, or executing a deployment. Deployment design itself is in scope.

## Council seated
| Persona | Seat | Why seated |
|---|---|---|
| rafachafa | Pragmatist Senior Dev | Simplest sufficient challenge delivery |
| gamachiel | Architect | Coherent model and SQL/auth boundaries |
| estebanquito | Engineering Manager | Checkable acceptance and sequencing |
| kings | Product | Exploratory value and scope discipline |
| ponykiller | Infra / SRE | Local persistence, refresh, resource limits |
| cuid | Risk & Verifiability | Broad SQL, identity, and role isolation |

## Mode & sizing
Greenfield system planning: three blind proposals, up to three debate rounds. Six seats, executed in batches to respect runtime concurrency. Canonical artifacts use `docs/specs/outage-explorer-backend/` to follow this repository's documented spec location; their headings and ID contracts follow the council's canonical templates.

## Intake result
All six independently identified authentication lifecycle, query breadth, refresh consistency/reproducibility, and operating constraints as the consequential questions. User resolved seeded-user scope and broad read-only SQL; refresh and runtime details remain explicit design assumptions to review. No stack or architecture has been accepted by the user.

## User pushback — shared deployment
The user rejected the Chair's subsequent laptop-only storage explanation. A focused mini-debate reopens D5/runtime and the topology-dependent parts of storage, metadata, refresh coordination and worker launching. This correction does not revoke seeded accounts, role boundaries or frontend deferral, and does not automatically mandate multiple replicas or cloud object storage.

## Topology resolution
The user then selected one replica for now. D11 records that decision and its limited scope: persistent storage and SQLite/application-owned refresh remain candidates; no full stack or hosting vendor was approved.

The user subsequently accepted separate persistent object storage for Parquet (D12). Backend analytical disk is temporary staging; provider/hosting and operational-state persistence remain open.

Current selection: the user requested documenting Amazon S3 + Parquet + DuckDB
after comparing it with persistent-disk-only DuckDB. D13 and
[ADR-0001](../../../adr/0001-s3-parquet-duckdb.md) record that choice. Earlier
provider/engine-open statements above describe the discussion at that time.
Backend hosting, operational-state persistence, and remote reads versus
staging remain open. ADRs are the accepted decision records; no separate
decisions file is needed.
