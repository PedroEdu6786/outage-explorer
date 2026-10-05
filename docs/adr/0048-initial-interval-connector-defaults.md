# ADR-0048: Connector defaults admit the initial interval

Status: **Accepted by user direction**

Date: 2026-10-04

## Context

The user requested the plain Make command for April 2–October 1, 2026,
without a JSON profile. The phase-4 defaults retained by ADR-0041 reject its
183-day interval at configuration validation. The phase-6 diagnostic retrieved
all three routes but did not finish repeated model/replay verification within
its explicit 300-second budget. Increasing admission does not prove completion.

## Decision

Replace ADR-0041's small initial budget values with bounded contributor defaults
that admit the accepted initial interval. Preserve its typed settings, optional
JSON field overrides, explicit flag precedence, environment-only credentials
and validation before source/storage work.

Source defaults: 183 days, 500 rows/page, 30,000 aggregate rows, 100 pages,
200 aggregate request attempts, three attempts per request, 10-second request
timeouts and a 1,800-second complete candidate budget. Per-response bytes are
1 MB; aggregate response/output bytes are 30/40 MB. Model incoming/prior/output
row limits are 30,000 and its interval limit is 183 days.

Artifact storage is capped at 256 MB. Logical buffer admission is 256 MB and
temporary/staging admission is 600 MB, enough for both artifact/readback graph
envelopes plus up to three staged 2-MB files. Both worker counts remain one by
default. S3 transfer/replay has a separate 1,800-second budget, 10-second request
timeouts and 1.6 GB aggregate attempted wire bytes; conditional writes,
request/object limits and exact complete readback remain required.

## Consequences

Plain Make can pass configuration validation for the initial interval without
reconstructing a recorded profile. JSON overrides can still tighten budgets or
select concurrency; no runtime automatically expands an exhausted limit.
Existing example profiles retain their explicit small settings.

These are validation allowances, not measured production budgets or a guarantee
that the full pipeline will complete. Recorded evidence remains unchanged;
T6.4/T6.C stay open until a candidate is fully verified. No live run, cloud write,
publication, activation, deployment or unbounded execution follows from this edit.
