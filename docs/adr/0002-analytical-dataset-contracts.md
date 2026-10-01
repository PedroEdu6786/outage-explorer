# ADR-0002: Define EIA analytical datasets through schema contracts

Status: **Accepted**

Date: 2026-10-01

## Context

The user accepted modeling EIA observations as analytical datasets and schema
contracts alongside the S3 + Parquet + DuckDB decision in ADR-0001. We need
explicit row meanings and validation rules even when persistent storage is
files. Exact source fields and relationships still require EIA investigation.

## Options considered

| Option | Benefits | Costs and limitations |
| --- | --- | --- |
| Analytical datasets with versioned schema contracts | Fits daily observations, Parquet storage and SQL analysis; makes validation and provenance explicit | Ingestion must enforce data rules before publication |
| ORM entities for every analytical row | Familiar object persistence and entity navigation | Adds mapping machinery without establishing constraints across Parquet files; no current transactional row-editing requirement |
| Query raw files using inferred schemas alone | Minimal initial transformation | Does not establish stable product names, units, keys or missing-value policies |

## Decision

- Describe EIA data as **analytical datasets and schema contracts**. Start
  with one dataset per source grain (the meaning of a single observation).
  Proposed SQL names are `national_daily`, `facility_daily`, `generator_daily`
  and the derived `fleet_offline_share_daily`; final schemas remain open.
- Define versioned contracts in the codebase covering columns, types, units,
  nullability, verified natural keys, source mappings and validation rules.
  Establish these from actual EIA metadata and records before implementation.
  Record the contract version with published datasets for reproducibility.
- Keep raw and modeled Parquet separate in S3. Ingestion transforms and
  validates records before publishing modeled data. DuckDB exposes the
  authorized modeled data under stable SQL names; remote reads versus staged
  in-memory tables remains an independent, unresolved loading choice.
- Do not require an ORM object for every observation. Introduce separate
  facility/generator reference datasets only when verified source identifiers,
  attributes and application needs justify them. Do not guess foreign keys.
- Preserve national, facility and generator observations independently.
  Reconciliation aggregates to a verified common grain before comparison;
  reported national totals are not replaced by facility sums. Legitimate
  discrepancies remain evidence rather than being silently corrected.
- Keep operational entities such as users, sessions and refresh runs in a
  separately durable operational store. Its engine remains undecided.

## Consequences

S3 stores the files, Parquet represents typed records, and DuckDB queries
them. Their combination does not automatically enforce cross-file key
uniqueness or business validity. Those checks belong to ingestion and
publication, with independent metric/reconciliation verification.

Retaining raw data, modeled data and historical snapshots intentionally
repeats information. The duplicate-prevention requirement concerns natural
keys within each published logical dataset, not eliminating evidence copies.

This decision accepts the modeling approach, not exact EIA schemas, a new
framework, or the draft refresh/retention mechanics. The [plan's integrity
proposal](../specs/outage-explorer-backend/plan.md#duplicate-prevention-and-data-integrity)
explains the required protections and remaining choices. No ingestion,
publication or query implementation exists yet.

## References

- [ADR-0001 — S3, Parquet and DuckDB](0001-s3-parquet-duckdb.md)
- [Backend specification](../specs/outage-explorer-backend/spec.md)
- [DuckDB Parquet support](https://duckdb.org/docs/current/data/parquet/overview)
