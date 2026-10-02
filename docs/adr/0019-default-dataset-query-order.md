# ADR-0019: Default ordering for dataset SQL queries

Status: **Superseded by [ADR-0020](0020-paginate-query-results.md)**

Date: 2026-10-01

## Context

The user requested default ordering after discussing unfiltered queries and
client-added limits. A query such as `SELECT * FROM generator_daily LIMIT 100`
should have an understandable order instead of relying on physical Parquet
file order. This is an application policy, not a claim that SQL clients always
add ordering.

## Decision

Apply a default outer result order to simple, row-preserving queries over one
product dataset when the query has no explicit outer `ORDER BY`. Ascending
date order follows the earliest-observations example discussed with the user;
the user did not separately specify ascending versus descending.

| Dataset | Default order |
| --- | --- |
| `national_daily` | `period ASC` |
| `facility_daily` | `period ASC, facility ASC` |
| `generator_daily` | `period ASC, facility ASC, generator ASC` |
| `fleet_offline_share_daily` | Observation date ascending |

These source field names are current model candidates. Resolve actual column
names and tie-breakers through the versioned schema contract once finalized.
Identifier ordering follows the declared column types; do not silently cast
text identifiers to numbers. Determinism depends on validated unique keys
within the selected snapshot.

- Preserve an explicit outer `ORDER BY`, including its direction and null
  ordering. Do not silently add tie-breakers to user-authored ordering.
- Apply the default before outer `LIMIT`/`OFFSET` chooses rows, rather than
  sorting an already limited or truncated response. Preserve explicit limits
  and offsets; server row/byte/runtime caps still apply independently.
- Use scope-aware parsed SQL and authorized source-column bindings, not
  string concatenation. Projection aliases must not redirect ordering away
  from the intended source keys. Ordering columns require authorization even
  when they are not projected. Never expose hidden sort keys in the response.
- Return the effective SQL and an indication of whether default ordering was
  applied, so the client can explain and reproduce the execution. Exact
  response field names remain open.
- Joins, aggregates, DISTINCT, CTEs, subqueries, set operations and other
  complex forms need a separate result-order policy. Until defined, preserve
  their supplied SQL without injecting guessed dataset keys. This does not
  exclude these queries from the broad analytical support in ADR-0012.
- Do not change inner ordering, window ordering, or limited subqueries while
  implementing a default outer order. A window's `ORDER BY` is not an outer
  result-order clause.

For example, the effective simple query is:

```sql
SELECT *
FROM generator_daily
ORDER BY period ASC, facility ASC, generator ASC
LIMIT 100;
```

## Alternatives and consequences

Leaving simple results unordered provides no chronological default. Adding
natural keys blindly to every query can change meaning or reference columns
that do not exist in aggregated results. The initial scoped policy establishes
the requested behavior while leaving complex result shapes for explicit design.

Sorting can increase execution work. Neither ordering nor limiting results
guarantees that only one Parquet file is scanned or downloaded. Existing
snapshot, authorization, cache and resource boundaries remain applicable.
Dataset-preview cursors remain governed by ADR-0015; this adds no SQL cursor
pagination or frontend implementation.

## Verification required

- Reverse file-list order and vary file boundaries: an eligible query must
  produce the same ordered rows on the same snapshot.
- Check default ordering before LIMIT/OFFSET across dates and partitions.
- Preserve explicit ascending/descending and expression-based ordering.
- Cover aliases, projections omitting keys, string identifiers and denied
  ordering columns without changing result columns or leaking data.
- Preserve complex-query results and inner/window ordering; keep default
  application metadata accurate, including server truncation.
- Measure sorting cost under the accepted execution and memory limits.

No API or query executor is implemented by this decision.
