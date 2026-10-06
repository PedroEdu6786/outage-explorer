# ADR-0058: Reset the active publication by user-directed SQL, without a reset CLI

Status: **Proposed** (records the user's direction of October 6, 2026; awaiting
user approval of this wording)

Date: 2026-10-06

## Context

[ADR-0057](0057-single-file-modeled-datasets.md) decided that a guarded operator
CLI operation, requiring the expected generation ID and refresh idleness, is the
only supported way to clear the active publication pointer before the fresh
single-file initial load. The compact-analytical-serving plan scheduled it as
phase 6 (use case, `RefreshStore` port method, PostgreSQL adapter, CLI, Make target
and architecture-rule registration).

While that CLI was being built, the user clarified that they wanted no new code:
only the data in PostgreSQL that referenced the old-layout S3 files removed. In a
separate session on October 6 that work was stopped and reverted before it was
committed, and the data was deleted directly. Per that session's recorded summary:

- the one `published_generations` row (the old-layout manifest reference) and the
  one `refresh_runs` row that produced it were deleted;
- `refresh_coordination.active_generation_id` was set to `NULL`;
- the `refresh_coordination` singleton row was kept.

The next refresh therefore admits as an initial load. This record does not
describe how the history immutability triggers were handled; the session's
summary in the devlog is truncated on that point.

## Decision

- Drop the reset CLI, use case, port method, adapter, Make target and its
  architecture-rule registration from the compact-analytical-serving plan. They
  are not implemented.
- The one-time reset needed for this change was performed by user-directed SQL.
  It is a recorded user decision, not a supported product operation.
- This supersedes only the "Publication reset" bullet of ADR-0057 and the
  matching rejected alternative "Reset by documented SQL". The remainder of
  ADR-0057 stands, including the single-file layout and the fresh initial load.

## Consequences

- No new application surface can clear the active pointer. A future reset of
  published data needs a new explicit user direction, and an ADR if it is meant
  to be repeatable or product-supported.
- The guards ADR-0057 specified (expected generation ID, refresh idle, latest run
  terminal and not `publication_unknown`) do not exist in code. Nothing in the
  repository prevents a repeated manual reset against valid data.
- The test item for a PostgreSQL reset operation is removed from the plan's test
  strategy. The initial-load path with no base generation remains covered.
- Preview and SQL stay unavailable until the new generation publishes, and EIA
  may return revised values, as already stated in ADR-0057.

## References

- [Spec](../specs/compact-analytical-serving/spec.md) and
  [plan](../specs/compact-analytical-serving/plan.md)
- [ADR-0052](0052-interrupted-refresh-recovery.md),
  [ADR-0057](0057-single-file-modeled-datasets.md)
