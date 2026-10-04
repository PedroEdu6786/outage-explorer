# Outage Explorer UI handoff for Astra

This portable context pack describes the web client to build in a separate
repository. It captures the user's selected stack and component architecture,
the product's accepted behavior, and the backend integration gaps as of
October 4, 2026. It does not claim that the product APIs or Figma implementation
are complete.

Copy this entire folder into the new repository at `docs/context/ui-client/`,
then paste the prompt below into Astra. The six files in this folder are
self-contained; the backend source references are optional verification material.
Supply the Figma file/frame links when starting design implementation. No Figma
URL or design contents were supplied for this handoff.

## Documents to load

| Order | Document | Purpose |
| --- | --- | --- |
| 1 | [Product scope](01-product-scope.md) | Purpose, personas, data meaning, expected capabilities and non-goals |
| 2 | [Web experience](02-web-experience.md) | User journeys, pagination behavior, visible states and Figma workflow |
| 3 | [Component architecture](03-component-architecture.md) | Atomic design, feature boundaries, Next.js structure and state ownership |
| 4 | [Backend integration](04-backend-integration.md) | Implemented versus specified behavior, auth, API seams and contract gaps |
| 5 | [Delivery and acceptance](05-delivery-and-acceptance.md) | Implementation sequence, verification, open inputs and source index |

Read all five before planning. During implementation, reload only the documents
relevant to the feature plus any newer agreed contracts. This pack summarizes
the current working tree, including uncommitted backend documentation; it is
not a released API contract.

## Copyable starting prompt

```text
You are working on the Outage Explorer web client in a separate repository
from its Python/Flask backend. Read docs/context/ui-client/01-product-scope.md
through 05-delivery-and-acceptance.md before planning or implementation.

We are building an authenticated analytical web app for exploring stored U.S.
nuclear outage observations from EIA at national, facility and generator grains.
Users discover permitted datasets and schemas, preview/filter records, inspect
the ready-made daily national offline-capacity metric, and run broad read-only
analytical SQL. Viewer access is national-only; Analysts can access all analytical
datasets; Admins have Analyst access plus the backend refresh capability.
An Admin screen is conditional, not part of the required initial UI.

Use React with Next.js, TypeScript and Tailwind CSS. An existing Figma design
governs the visual implementation. Inspect its actual frames, components,
variants, assets and tokens before making visual decisions; if its URL/access
is missing, request it and continue independent architecture/contract work.
Do not invent a replacement design or claim visual fidelity without inspection.

Organize components using atomic design:
- Atoms: reusable text, buttons, links, labels, inputs and similar primitives.
- Molecules: simple compositions of atoms with no product/domain logic.
- Organisms: contextual compositions that can display data/status and own
  cohesive UI interactions. Keep API transport and workflows outside them.
- Templates: reusable page layouts expressed through composition/slots.
- Pages: thin route-level composition of features and templates.
Keep feature hooks/services, API adapters and transport types outside shared
presentation components. Prefer clear typed props, accessible semantic HTML,
design tokens and actual reuse over speculative abstractions.

Preserve these behaviors: Cognito managed login with Authorization Code + PKCE;
one-hour application sessions, explicit re-login and current-session logout;
backend-authoritative permissions; snapshot-bound preview cursors; numbered SQL
pages from ONE execution with a fixed page size; explicit result expiry,
truncation and busy states. Never rerun SQL implicitly to paginate or retry a
failed execution. Never modify submitted SQL by adding pagination clauses.

The backend currently exposes GET /health only. Product behavior is specified,
but routes, payloads and session transport remain to be finalized. Use explicit
fixture adapters for independent UI development; label proposed contracts and
mock data. Never present fixtures as EIA findings or live integration.

The client consumes the authorized backend API. Do not access EIA, S3, RDS or
DuckDB directly, duplicate backend authorization/ingestion, add registration or
role management, infer outage causes/durations, or expand beyond agreed scope.

First provide a concise understanding of scope, a Figma-to-component inventory
(once accessible), a proposed structure and implementation sequence, and the
specific missing contracts. Distinguish requirements from recommendations.
Implement only when that work is requested; this prompt establishes context.
Report checks actually run and separate fixture validation, live integration
and visual comparison results.
```
