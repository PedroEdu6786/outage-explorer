# ADR-0049: Bounded page prefetch and explicit worker flags

Status: **Accepted by user direction**

Date: 2026-10-04

## Context

The user clarified that parallel fetching means pages within one EIA route,
not only independent endpoints, and requested a plain Make command selecting
fetch and S3 workers. EIA offsets advance by received count, advertised facility
totals disagree with received rows, and short pages are not terminal.

## Decision

Add independent typed `workers.page_workers` (1–3, default1), CLI
`--fetch-workers`/`--s3-workers` overrides and Make `FETCH_WORKERS`/`S3_WORKERS`.
Explicit flags override JSON. Existing endpoint workers remain compatible and
stay1 by default. Preserve ADR-0048 resource allowances unchanged.

Use bounded speculative windows at offset+k*page_length. Fetch concurrently,
then consume by offset/row order; full pages advance through the window, short
pages repair the next offset from received count, and only the canonical first
empty page terminates. Never use advertised totals for termination. Every
admitted request must succeed and validate, including unused lookahead.

Preserve every sanitized successful window response as a content-addressed
transport JSON object referenced by evidence/manifests, including request identity,
received time, offset, parameters, attempts/redactions and full envelope. Canonical
raw/page Parquet remains contiguous with exactly one terminal. Supplementary
objects are integrity-checked, budgeted and recovered as graph dependencies;
unused lookahead is audit evidence, never additional modeled observations.
Backward-compatible manifests omit the optional supplementary field when empty.

Share aggregate requests/retries, response/output bytes, fetched rows, pages,
deadline and endpoint*page buffer admission. Cancellation stops new windows and
joins all page workers before transport cleanup. No total-based completeness,
source-recency, publication or model speedup guarantee follows.

## Consequences

Parallel mode can spend extra requests/rows/bytes on audited lookahead and repair;
it may exhaust a budget sooner than sequential mode. Normal sequential behavior
and existing exact source/model replay remain available. Synchronous modeling
and repeated replay remain the measured bottleneck. No full live initial run
is authorized or required by this extension.
