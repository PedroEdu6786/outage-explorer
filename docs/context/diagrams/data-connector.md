# Data connector: high-level flow

The connector retrieves all three EIA grains and constructs a verified candidate.
Persistence makes its three files durable; the product refresh workflow separately
publishes them. A contributor CLI run never activates product data.

```mermaid
flowchart TD
    CLI["Connector CLI<br/>Explicit bounded dates"] --> Config["Validate configuration and bounds<br/>Validate S3 target before source work<br/>unless explicitly local-only"]
    Worker["Independent refresh worker<br/>Admitted configuration and fenced ownership"] --> Config
    Config --> Retrieve["Retrieve and sanitize bounded pages<br/>National, facility, generator"]
    EIA["EIA API v2"] --> Retrieve
    Retrieve --> Inputs["Bounded transient candidate inputs"]
    Inputs --> Model["Validate, select, calculate and merge"]
    Prior["Verified prior resource files<br/>when a baseline exists"] --> Model
    Rules["Shared pure domain policies<br/>Identity, duplicates, revisions, retention"] -.-> Model
    Model --> Verify["Build and verify candidate<br/>Three typed Parquet resource files<br/>with private provenance"]
    Verify --> Outcome{"Candidate outcome"}
    Outcome -->|"All incoming rows excluded"| Retained["Report retained outcome<br/>Keep active generation unchanged"]
    Outcome -->|"Usable candidate"| Mode{"Persistence mode"}
    Mode -->|"CLI local-only"| Local["Local verified candidate and report<br/>No publication"]
    Mode -->|"Default CLI or product refresh"| Persist["Persist exactly three files in S3<br/>Full durable readback and integrity checks"]
    Persist --> Receipt["Exact durable receipt<br/>Keys, checksums, bytes, rows and coverage"]
    Receipt -->|"CLI"| Done["Return durable candidate result<br/>No publication"]
    Receipt -->|"Product refresh"| Publish["Recheck owner, lease and baseline<br/>Commit descriptors, quality, run success<br/>and active pointer in PostgreSQL"]
    Publish --> Readers["New reads use the new generation<br/>Existing reads retain their snapshot"]
```

Each resource file is `national.parquet`, `facilities.parquet` or
`generators.parquet` under the configured generation prefix. Raw pages,
dispositions and merge ledgers are transient; no supporting S3 graph or manifest
is produced. Failed retrieval, exhausted bounds or failed durable readback
cannot become success through a local-only fallback. Publication uncertainty
requires reconciliation, not a blind retry or pointer change.

| Responsibility | Source |
| --- | --- |
| Candidate orchestration | [CreateResourceCandidate](../../../src/outage_explorer/application/services/connector.py) |
| EIA retrieval and sanitization | [EIA adapters](../../../src/outage_explorer/infrastructure/eia/) |
| Candidate inputs, building and verification | [Parquet adapters](../../../src/outage_explorer/infrastructure/parquet/) |
| Durable persistence and recovery | [Resource artifact services](../../../src/outage_explorer/application/services/resource_artifacts.py) |
| Product execution and publication orchestration | [Refresh execution](../../../src/outage_explorer/application/services/refresh_execution.py) |
| Durable coordination/publication | [PostgreSQL publication](../../../src/outage_explorer/infrastructure/postgresql/publication.py) |

The diagram shows the current composed source, not a newly executed live run.
Initial publication needs usable data in every grain. Later merges preserve
absent/invalid prior rows under [ADR-0037](../../adr/0037-connector-initial-load-and-retention.md).
An active base without exact resource descriptors fails closed under
[ADR-0064](../../adr/0064-remove-obsolete-manifest-publication-columns.md), which
removes the obsolete manifest columns and publication adapter.

[All module diagrams](../module-diagrams.md) · [Decisions](../../../DECISIONS.md)
