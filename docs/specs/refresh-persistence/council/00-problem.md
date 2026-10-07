# Refresh persistence optimization — Problem Anchor

## The Main Problem
Refresh persistence takes too long because it creates, uploads, and verifies 1,442
separate S3 objects per generation (supporting raw batches, page descriptors,
dispositions, and daily ledgers) that are never consumed by API clients, DuckDB
queries, or challenge deliverables. Optimize refresh persistence by persisting
strictly the three canonical resource Parquet files (national, facility, generator)
per generation with bounded upload concurrency, eliminating all durable supporting
artifacts.

## Context
- The user observed excessive S3 persistence duration and noted that hundreds of
  persisted supporting files are unused overhead.
- Generation `09939495…` (183 days) produced 1,442 objects totaling ~57.5 MB:
  3 modeled, 3 public, 549 dispositions, 549 ledgers, 277 raw batches, 60 page
  descriptors, and 1 manifest.
- DuckDB preview and SQL queries only read the public dataset files.
- Subsequent refresh merges only require prior accepted rows to perform absence
  retention and replacement.
- Transient quality metrics (counts and exclusion codes) are preserved in
  PostgreSQL `refresh_runs.quality_json` under ADR-0025.
- Technical challenge requirements are fully satisfied without archiving arbitrary
  discarded rows in S3; challenge anomaly evidence (Finding 001) is preserved in
  repository test fixtures and documentation.
- Formally recorded in ADR-0060, superseding the 6-file and audit-preservation
  clauses of ADR-0057.

## Known constraints
- ADR-0060 (Proposed): exactly 3 Parquet files per generation in S3.
- ADR-0025: Admin refresh quality summary stored in PostgreSQL.
- ADR-0052: recovery fencing and atomic publication in PostgreSQL.
- One-to-three bounded transfer workers with shared aggregate bounds.
- Layered Python/Flask monolith architecture.

## Out of scope (declared up front)
- S3 bucket lifecycle / mass deletion of historical objects.
- Public HTTP API schema changes.
- DuckDB sandbox or query execution engine redesign.

## Council seated
| Persona | Seat | Why seated |
|---|---|---|
| rafachafa | Pragmatist Senior Dev | Simplest 3-file persistence pipeline |
| gamachiel | Architect | Unified schema and PostgreSQL publication metadata |
| estebanquito | Engineering Manager | Phased sequencing and delivery acceptance |
| kings | Product | Maximum user value and performance improvement |
| ponykiller | Infra / SRE | S3 operations reduction (~4,326 → 9) and resource safety |
| cuid | Risk & Verifiability | Pre-upload transient verification and exact readback |
