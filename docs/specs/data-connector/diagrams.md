# Data connector diagrams

The current [high-level data connector diagram](../../context/diagrams/data-connector.md)
shows EIA retrieval, transient candidate inputs, shared model policies, exactly
three verified Parquet resources, S3 durable readback and separate PostgreSQL
publication. It includes the local-only and retained-data outcomes.

This replaces the October 4 diagrams that described candidate manifests and
durable supporting evidence graphs. Those layouts were superseded by accepted
[ADR-0060](../../adr/0060-persist-only-three-resource-files-per-generation.md)
and are no longer the current connector flow.

For the adjacent functional areas, see the [endpoint diagram](../../context/diagrams/endpoints.md)
and [model/verification diagram](../../context/diagrams/model-verification.md).
The [module diagram index](../../context/module-diagrams.md) links all three;
[DECISIONS.md](../../../DECISIONS.md) explains their rationale.

These are source-level responsibilities, not a fresh live run or deployment
acceptance. The [refresh-persistence checkpoints](../refresh-persistence/tasks.md)
record the current controlled implementation scope.
