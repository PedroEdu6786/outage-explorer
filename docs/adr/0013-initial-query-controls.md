# ADR-0013: Accept initial query isolation and limits

Status: **Accepted starting settings; runtime verification pending**

Date: 2026-10-01

## Context and decision

The user accepted the proposed query controls while leaving data validation
rules open for further discussion. This refines ADR-0007's bounded execution
approach without selecting the concrete sandbox runtime.

- Run analytical SQL in an isolated DuckDB worker with only authorized
  Parquet files, no credentials and no network access.
- Admit one analytical query at a time initially; additional queries receive
  a retryable busy response. Other API operations remain available.
- Start with a 10-second SQL execution deadline. Bound preparation separately;
  the preparation/overall deadline value remains to be measured.
- Enforce a worker memory ceiling and set DuckDB's memory budget below it.
  Exact sizes are not yet selected.
- Cap returned results at 1,000 rows or 1 MiB of serialized output, whichever
  is reached first, with explicit truncation metadata. Bound fetching and
  serialization; a result cap does not limit query work by itself.
- Budget temporary disk and the reusable Parquet cache separately, based on
  measurements of representative extraction and queries.

## Alternatives and consequences

Higher initial concurrency adds resource contention before workload sizing
exists. Unbounded execution can disrupt the API. These controls provide a
measurable starting configuration and may be tuned with documented evidence.
They do not establish that queries fit, finish within the deadline, or that
the runtime isolation already works. Verify failure isolation and combined
API/query/refresh capacity before release.

The earlier candidate 1 CPU, 1 GiB worker and 30-second total lifetime are
not accepted values by implication. Concrete runtime, memory/disk sizes,
CPU allocation and total preparation deadline remain open. No application
code or infrastructure is introduced by this record.
