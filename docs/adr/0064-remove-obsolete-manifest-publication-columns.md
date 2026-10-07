# ADR-0064: Remove obsolete manifest publication columns

Status: **Accepted** (explicit user direction, October 7, 2026)

## Context

The current publication path stores three exact resource descriptors in
`published_generations.datasets` under ADR-0060/0061. The previous implementation
used `manifest_key` and `manifest_digest`; ADR-0062 retained those columns to
distinguish old rows. The user explicitly directed their removal because the
previous implementation is no longer used.

## Decision

Supersede ADR-0062's column-retention and dual-layout adapter decisions. Forward
migration `0005_remove_manifest_columns` drops both columns and replaces the
layout check with `resource_generation_valid(id, datasets)`. Remove the obsolete
manifest publication adapter and domain contract; current publication reads,
admission and writes use exact resource descriptors alone.

The check is added `NOT VALID` so existing historical summaries need no invented
descriptors or destructive row cleanup. PostgreSQL enforces it on every new or
updated row. Existing generation IDs, dataset JSON, run references, foreign keys,
immutability triggers and coordination pointers remain unchanged. Readers and
base admission reject summaries lacking valid exact descriptors. No old-layout
fallback, conversion, reset or row deletion is introduced.

## Consequences

The ER describes only current publication columns. Legacy manifest values are
discarded; downgrade refuses rather than inventing their previous values. Old
rows without resource descriptors remain unreadable, preserving the fail-closed
behavior of ADR-0062 without obsolete columns.

Application code and schema must move together: earlier adapters reference the
removed columns. This decision authorizes the requested schema cleanup, not
publication-history deletion, active-pointer resets or new source retrieval.
