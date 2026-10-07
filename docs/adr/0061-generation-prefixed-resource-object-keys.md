# ADR-0061: Generation-prefixed resource object keys

Status: **Accepted** (explicit user choice, October 6, 2026)

## Context

[ADR-0060](0060-persist-only-three-resource-files-per-generation.md) selects
exactly three unified resource Parquet files per generation. The existing graph
adapter addresses objects by checksum under `objects/`, while the refresh
persistence plan specifies a generation prefix. Gate G4 requires an explicit
mapping shared by persistence, publication descriptors and recovery.

## Options considered

- Generation-prefixed keys group each generation's three files and match the plan;
  matching content in different generations occupies separate objects.
- Shared `objects/<sha256>` keys reuse identical content across generations, but
  do not provide the plan's generation grouping and require a different physical
  publication contract. Both options support conditional writes and exact readback.

## Decision

The user selected generation-prefixed keys:

```text
<configured-prefix>generations/<generation-id>/national.parquet
<configured-prefix>generations/<generation-id>/facilities.parquet
<configured-prefix>generations/<generation-id>/generators.parquet
```

The configured bucket and normalized prefix remain fixed adapter configuration.
Generation IDs must be validated as safe single path segments. Internal grain
identifiers remain singular; physical filenames follow the existing public names.
Local content identity remains SHA-256; it is distinct from the physical S3 key.
Durable descriptors retain both identities, byte count, row count and schema
identity, with the candidate interval, versions and baseline identity in the receipt.

Writes remain single conditional `PutObject` operations with `IfNoneMatch="*"`
and `ChecksumSHA256`. Success requires complete byte-count and SHA-256 readback
of each exact key. An existing key is accepted only after exact verification;
conflicting bytes fail. Recovery uses supplied descriptors, validates their
mapping and verifies the three files without discovering metadata through HEAD,
listing, manifests or source requests. All workers share aggregate transfer
bounds and must finish before shared staging cleanup.

## Consequences

Each generation owns three immutable physical addresses, even when file contents
match another generation. Receipts and subsequent PostgreSQL publication must
record those addresses rather than infer keys from checksums. No fourth manifest
object is introduced.

This resolves G4 for Phase 2 implementation. Shared CLI/refresh/bootstrap
composition changes in Phase 4. G3 still requires a history-preserving rollout,
cutover and rollback decision before Phase 3 migration/runtime use. This decision
does not authorize cloud calls, a live load, activation, pointer resets, deletion
or migration of historical objects.
