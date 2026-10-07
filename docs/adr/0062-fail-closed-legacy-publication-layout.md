# ADR-0062: Fail closed on a manifest-format active publication

Status: **Accepted** (explicit user choice, October 6, 2026)

## Context

[ADR-0060](0060-persist-only-three-resource-files-per-generation.md) replaces the
manifest/six-file graph with three exact resource descriptors per generation.
Gate G3 asked how an existing active manifest-format generation behaves once
resource-format rows exist, without conversion, invented descriptors, a pointer
reset or deletion ([ADR-0058](0058-user-directed-publication-reset.md) was a one-time
direction, not standing permission).

## Options considered

- **Fail closed on an old base:** preserve the old rows and pointer, never read or
  extend them with the new code.
- Read old rows through the manifest path: keeps data queryable but retains the
  old-layout compatibility code the project forbids.
- A user-directed one-time reset: valid only as a separate explicit instruction.

## Decision

The user selected fail-closed behavior. Migration
`0004_refresh_resource_files` makes `published_generations.manifest_key` and
`manifest_digest` nullable and adds a database constraint: a row is either
manifest-format (both columns present) or resource-format (both NULL and
`datasets` holds exactly three distinct-grain descriptors with `object_key`,
lowercase SHA-256, positive `byte_count`/`rows`, coverage dates and the exact
`generations/<generation-id>/<file>.parquet` key). Existing rows, foreign keys,
coordination and immutability triggers are untouched; nothing is backfilled.

The resource publication store (`PostgresqlResourcePublicationStore`) raises
`UnsupportedPublicationLayoutError` instead of reading, admitting a refresh over,
or publishing over a manifest-format active base; the manifest store symmetrically
refuses resource-format rows. Both reject before any state change. Moving past an
incompatible base requires a separate, explicit user-directed reset or cutover
decision; this ADR grants none and adds no reset CLI.

Downgrade fails explicitly once any resource-format row exists, because the
immutable history cannot be rewritten; with only manifest-format rows it restores
the original NOT NULL constraints.

## Consequences

The first resource-format publication after this migration requires either an
empty publication history or that separate direction. Runtime activation, live
loads, deletion and managed-database migrations remain unauthorized. Shared
CLI/refresh/bootstrap composition still switches in Phase 4.
