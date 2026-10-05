# ADR-0050: Replay-derived day indexes during candidate verification

Status: accepted (user-directed connector stall correction, October 4, 2026).

## Context

Verification scanned an entire evidence bundle for every requested day and again
for each retained-history day. A183-day candidate therefore repeated decoding
and semantic evidence checks hundreds of times before comparison completion.

## Decision

Rebuild deterministic content-addressed raw day partitions once per evidence
bundle during each verification. Reuse the existing bounded `stage_dates` writer,
not prior verified metadata. Verify all original evidence, modeled values,
origins, quality, dispositions, ledgers and ancestry as before. Stage inherited
bundles only for the current grain, once, and read only the required day.

Verification now may create local immutable staging objects. They share the
configured store object/byte/batch/deadline limits and temporary-disk admission;
identical existing objects are hash checked. They are derived artifacts, not
manifest dependencies or authoritative data, and never cause S3 writes. Preserve
immutable staging after failure for retries, matching existing build behavior;
atomic writer temporary files are cleaned on failure. Recovery may consume more
local staging space than the durable graph and fails closed when its store budget
is exhausted. No whole-history rows are retained in RAM.

## Alternatives and consequences

Read-only per-day rescans preserve no-write verification but cost O(days*rows).
A separate temporary store adds accounting/cleanup complexity. Existing immutable
staging keeps one accounting boundary and deterministic ordering, at the cost of
bounded local writes. Grain and periodic day progress logs expose ongoing work;
this does not parallelize modeling or prove production budgets.
