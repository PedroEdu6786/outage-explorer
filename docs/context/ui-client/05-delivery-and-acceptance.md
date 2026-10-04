# Delivery and acceptance

Use this checklist in the separate UI repository. The handoff authorizes
context preparation; it does not itself provision a repository, deploy an app
or declare a visual/API integration complete.

## Suggested implementation sequence

1. Read this pack and the destination repository's instructions. Inspect Figma
   when access is supplied; map screens and repeated elements to components.
2. Record the small set of remaining architectural choices: App Router setup,
   package versions/tooling, auth transport and API adapter contract. Keep
   confirmed requirements distinct from recommendations and unresolved choices.
3. Establish tokens, semantic atoms, molecules and reusable templates. Build
   an isolated component preview using the project's chosen tooling.
4. Build catalog/preview/metric and SQL feature compositions against explicit
   fixtures. Exercise loading, permissions, pagination and recovery early.
5. Integrate the agreed real session and API contracts as they become available.
   Verify every persona and same-execution pagination with the backend.
6. Compare rendered screens with the actual Figma frames, check responsive and
   keyboard behavior, and document the setup and remaining gaps.

Proceed with independent work when an API or design input is missing; only
block the dependent work. Do not invent the missing contract or visual evidence.

## Acceptance criteria

- The selected Figma screens are implemented with traceable component/token
  mappings. Differences and added states are explicitly documented.
- Shared atoms/molecules have no product logic or network calls. Organisms are
  cohesive, templates are reusable, and route pages remain thin. Feature
  workflows and API transport have clear owners.
- Sign-in/session expiry/logout follow the real agreed backend behavior.
  No protected-data flash or stale result restoration occurs after logout.
- Viewer navigation, schemas, filters, autocomplete, previews, metrics and SQL
  expose national data only. Direct unauthorized backend requests are denied;
  UI hiding alone is not evidence of enforcement.
- Preview filters reset the browsing sequence; continuation remains on one
  snapshot and expiry offers an explicit restart.
- SQL Run initiates one execution. Numbered page navigation and revisit send
  the query ID and fixed page size without another execution or SQL rewriting.
- Empty, duplicate-row, duplicate-column-label, busy, timeout, truncated,
  lost/expired and denied SQL cases have correct observable behavior.
- Metric labels, units, nulls, dates and two-decimal half-up presentation agree
  with the accepted national contract. No match/mismatch flags or invented
  causes, durations or missing observations appear.
- If an Admin screen is included, refresh outcome and retention/exclusion
  accounting are accurate, with automatic publication and no approval step.
- Keyboard navigation, focus, labels, status announcements and narrow-screen
  table/editor usability are checked. Any scoped chart has an accessible
  representation of its data.
- Fixture mode is explicit, isolated from production and never described as
  live integration. Runtime failures do not silently activate mock data.

## Deferred improvement after current delivery

The user accepted a future **new data available** status card in ADR-0040
(`docs/adr/0040-defer-new-data-status-card.md` in the backend repository).
When a view shows an older snapshot, the card will offer an explicit refresh
to retrieve the backend's current published data. The backend assigns the
active snapshot; users do not select versions or trigger EIA ingestion through
this card. Existing pages remain bound to their original snapshot/execution;
updated SQL results require an explicit new execution, never an automatic rerun.

Implement this only after the current agreed work is complete. It is excluded
from the acceptance criteria above. Metadata, detection mechanism, placement,
and exact interaction remain to be designed.

## Verification to report

Run TypeScript, lint and production-build checks selected by the UI repository.
Test meaningful behavior at the component/feature seam: filter resets, stale
responses, fixed query page size, no implicit execution retries and recovery
from unavailable result state. Add browser flow tests for login, catalog,
preview and SQL using controlled fixtures first, then real integration where
available. Include negative access cases and cross-session client-state cleanup.

Use request observations to verify that changing SQL pages never submits SQL
again. Include a refresh/snapshot transition and backend query-state loss in
integration coverage. For presentation, compare actual rendered screens with
the supplied Figma frames at relevant widths; screenshots of fixture-only
screens do not prove production integration or backend security.

Report which checks ran, which adapter/environment was used, and what remains
unverified. Do not infer runtime permissions from types, component structure
or successful compilation.

## Inputs still needed for implementation

| Input | Work it affects |
| --- | --- |
| Destination UI repository and its existing setup | Scaffolding and tooling |
| Figma URL, relevant nodes, assets and access | Visual inventory and fidelity |
| Backend environment and version | Live integration |
| Agreed routes, DTOs, errors, SQL names and data encoding | HTTP adapter |
| Cognito callback/client configuration and session transport | Real login/logout integration |
| SQL page defaults/maxima, TTL, retry/error details | Final SQL controls and messages |
| Inclusion of Admin UI and any optional charts/findings | Scope beyond the core workflows |
| Target viewports and any additional accessibility/browser requirements | Design extensions and verification matrix |
| Frontend hosting, domain and release configuration | Deployment; independent of UI implementation |

## Backend source index

These are repository-relative paths in the **backend** repository, not required
imports into the UI repository. The pack already summarizes the needed content.
Consult newer contracts if the backend has progressed beyond this snapshot.

| Source | Authority for this handoff |
| --- | --- |
| `docs/context/overview.md` | Product promises, personas and challenge scope |
| `docs/specs/outage-explorer-backend/spec.md` | Product requirements; still a draft with historical/open sections |
| `docs/adr/0039-separate-ui-client-atomic-design.md` | User-selected separate UI repo, stack and component hierarchy |
| ADR-0014, ADR-0016, ADR-0017, ADR-0018 | Session experience, application-owned permissions and Cognito OAuth2; ADR-0017 removes required OIDC |
| ADR-0015 | Preview cursors, defaults and expiry |
| ADR-0012, ADR-0013, ADR-0020, ADR-0021, ADR-0022 | Broad read-only SQL, baseline limits, one-execution numbered pages and ephemeral state |
| ADR-0006, ADR-0027, ADR-0031, ADR-0035 | National metric, required values, percentage presentation and meaning |
| ADR-0003, ADR-0025, ADR-0026, ADR-0037 | Refresh activation, visible quality accounting and retained-data policies |
| ADR-0030, ADR-0032, ADR-0038 | Current Flask structure, PostgreSQL/RDS and EC2 deployment |
| `docs/specs/national-data-verification/contract.md` | Bounded national schema, units, precision and evidence limits |
| `docs/specs/facility-generator-verification/contract.md` | Detail keys/identifiers and source-completeness caveats |
| `src/outage_explorer/entrypoints/http/app.py` and `routes/health.py` | Currently registered HTTP behavior |

All ADR files live under `docs/adr/`. Older ADRs retain historical mentions of
FastAPI, SQLite, ECS and default SQL ordering. Those parts are superseded;
do not revive them when reading individual records. The backend's Python
directory layout, dependency checks and Git workflow do not automatically
govern the new TypeScript repository.
