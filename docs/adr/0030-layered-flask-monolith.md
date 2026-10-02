# ADR-0030: Use a documented layered Flask monolith

Status: **Accepted by user direction**

Date: 2026-10-01

Replaces the proposed structure in [ADR-0029](0029-modular-clean-architecture.md).

## Context

After reviewing the alternatives, the user accepted a layered application and
a monolith, and requested explicit project structure so agents preserve it.
The request for an independent-services example is explanatory, not a topology change.

## Decision

Use one Python/Flask application and release with a layer-first package layout:
`domain`, `application`, `infrastructure`, and `entrypoints`, wired by `bootstrap`.
Use a service layer and small application-owned interfaces to keep policies
independent of Flask, databases, cloud SDKs, and analytical libraries.

The [code structure guide](../context/code-structure.md) defines responsibilities,
allowed imports, examples, and verification requirements. Root
[AGENTS.md](../../AGENTS.md) makes those rules mandatory for project agents.
Separate background and isolated analytical execution remain part of the same
product; their concrete runtime topology is still open.

## Alternatives and consequences

- Feature-first layered modules were the previous proposal. Prefer one shared
  layer hierarchy for the accepted simpler structure; keep feature grouping
  within layers where useful.
- Independently deployable services remain deferred. They require network
  contracts, authenticated delegation, and explicit per-service state ownership.
- Unrestricted route-to-database layering would be easy to start but would not
  preserve reusable authorization and framework-independent policies.

Documentation guides agents but cannot guarantee compliance. Add automated
import-boundary checks and CI enforcement with the first application scaffold;
verify security and state guarantees with behavior and integration tests.
No application code, deployment, additional dependency, or infrastructure
resource is introduced by this decision.
