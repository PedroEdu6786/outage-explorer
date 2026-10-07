# High-level module diagrams

These diagrams explain the three main functional areas of the layered Flask
backend. They are parts of one product, not independently deployed services.
Concrete dependencies are injected by `bootstrap.py`. Mermaid renders the
diagrams in GitHub and compatible Markdown previews.

| Area | Diagram | Main question |
| --- | --- | --- |
| [Data connector](diagrams/data-connector.md) | Retrieval, candidate construction, persistence and publication | How does EIA data become a published generation? |
| [API endpoints](diagrams/endpoints.md) | One flow diagram per HTTP operation, with authorization, processing and response | What happens inside each endpoint? |
| [Model and verification](diagrams/model-verification.md) | Shared domain rules, typed resources, offline replay and reconciliation | How do we establish identity, correctness and evidence? |

Reviewed against current workspace source on October 7, 2026. These diagrams
describe code responsibilities and accepted behavior, not a fresh live test or
managed deployment. The [refresh checkpoints](../specs/refresh-persistence/tasks.md)
and [runtime evidence](../specs/data-api/runtime-evidence.md) record acceptance
scope. See [DECISIONS.md](../../DECISIONS.md) for rationale and
[the ER diagrams](data-model.md) for entities, attributes and relationships.
