# Component architecture

**User requirements:** a separate UI repository using React, Next.js,
TypeScript and Tailwind CSS; an existing Figma design; reusable atoms,
domain-free molecules, contextual organisms, reusable templates and thin pages.

**Recommended implementation approach:** the App Router layout and module
boundaries below. These are handoff recommendations, not previously approved
library, hosting or authentication-transport decisions. Adapt filenames to real
features without weakening the separation of responsibilities.

## Atomic design responsibilities

| Level | Responsibility | Examples | Keep outside |
| --- | --- | --- | --- |
| Atoms | Small reusable visual primitives with semantic HTML, typed variants and accessibility | `Text`, `Button`, `Link`, `Label`, `Input`, `Badge`, `Spinner` | Product types, permissions, API calls and workflows |
| Molecules | Simple domain-free compositions with generic interaction behavior | `FormField`, `SearchField`, `SelectField`, `EmptyState`, `PaginationControls` | Dataset rules, role checks, query IDs and network requests |
| Organisms | Cohesive contextual sections; combine primitives, data, statuses and local UI behavior | `DatasetCatalog`, `DatasetPreview`, `SqlEditorPanel`, `QueryResults`, conditional `RefreshOutcome` | HTTP parsing, token storage, authorization policy and backend business rules |
| Templates | Reusable page structure through slots/composition | `AppShell`, `ExplorerTemplate`, `WorkspaceTemplate` | Endpoint knowledge, data fetching and feature-specific workflow decisions |
| Pages | Route-specific assembly of templates and feature entry components | Next.js `app/**/page.tsx` | Large UI bodies, repeated layouts, inline transport and duplicated orchestration |

The levels describe responsibility, not mandatory wrapping. An organism can
compose atoms directly. Do not wrap every HTML element or create empty layers
just to fill the hierarchy. Promote a component to shared code when its API
and behavior are useful across contexts, not merely because two fragments look
similar. Prefer slots and small variants to a universal component with many
unrelated boolean props.

An organism may interpret presentation context, such as showing a running
status or a truncation notice. Feature hooks/services own query submission,
pagination lifecycle and error recovery. The backend owns authoritative
permissions, SQL validation, metrics and publication rules.

## Suggested source layout

```text
src/
  app/
    layout.tsx
    globals.css
    (public)/
      sign-in/page.tsx
    (protected)/
      layout.tsx
      datasets/page.tsx
      datasets/[datasetId]/page.tsx
      query/page.tsx
      loading.tsx
      error.tsx
  components/
    atoms/
    molecules/
    organisms/                 # only cross-feature organisms
    templates/
  features/
    auth/
    catalog/
    preview/
      components/organisms/
      hooks/
      services/
      types.ts                 # feature/view types, not raw transport DTOs
    queries/
    metrics/
    # refresh/ only if an Admin UI is included
  lib/
    api/
      contracts/               # agreed transport types and validation
      adapters/                # HTTP-to-feature mapping
      client.ts
      errors.ts
    auth/                      # selected session integration
    config/
  styles/
    tokens.css
  test/
    fixtures/                  # explicit, development/test-only data
    adapters/                  # fixture implementation of the API seam
```

The route names are suggestions pending Figma review. Do not create duplicate
`components/pages` implementations: route pages are the page level. Atomic
templates are ordinary layout components; they do not require Next.js's
special `template.tsx` file or its lifecycle semantics. Feature directories
need only the subfolders actually used.

## Dependency direction

Shared atoms and molecules depend only on lower-level shared UI and small
domain-free helpers. Shared organisms compose shared primitives. Feature
organisms can use their own feature types and shared UI. Templates arrange
slots and shared UI; they do not import product workflows. Pages and feature
entry components compose these pieces and connect feature hooks/services.

Feature services use a typed API seam. HTTP adapters own URLs, transport DTOs,
response validation and mapping. Shared UI never imports features, `app/`,
transport adapters or auth/session storage. Features should not reach into
another feature's internals; use a narrow public contract when needed.

For example, `PaginationControls` receives the current page, available actions
and callbacks. `QueryResults` presents those controls and query status. A query
feature hook tracks `query_id`, the fixed page size and loading state, and calls
the adapter. None of these UI components appends SQL clauses or validates access.

## Next.js and React boundaries

With App Router, retain server rendering for suitable layouts and initial
composition. Use Client Components where interaction, state or browser APIs
are required, such as the SQL editor and filter controls. Keep client boundaries
focused rather than marking the entire app as client-rendered. Data crossing
the server/client boundary must be suitable for serialization; credentials and
server-only code must stay server-side. See the official
[Next.js component guidance](https://nextjs.org/docs/app/getting-started/server-and-client-components).

Atomic level and execution environment are independent: an atom can need a
client boundary, while an organism can render on the server. Choose based on
behavior. Keep one owner for each state and derive display values when possible,
following [React's component and state guidance](https://react.dev/learn/thinking-in-react).

Next.js is the presentation tier. A thin server-side API/session bridge may be
selected during integration, but it must delegate product operations to Flask.
Do not introduce a second SQL engine, database-backed business backend or
independent permission implementation in Next.js route handlers/server actions.

## State ownership

| State | Suggested owner |
| --- | --- |
| Focus, expanded panel, local input editing | Closest cohesive component |
| Applied dataset/date/facility selection | Feature controller; URL when useful and safe |
| Identity and current capabilities | Auth integration scoped to the current session |
| Preview cursor and snapshot | Preview feature state |
| Draft/submitted SQL, query ID, fixed size and selected page | Query feature state |
| HTTP response shape and normalized failures | API adapter |

Never put access tokens, session credentials or query SQL in URLs. Do not
globally persist protected results or credentials. Scope any response cache
to the current identity, permissions, parameters and execution/snapshot; clear
it on logout or identity/access changes. Disable execution-triggering retries
and refetches for SQL. Ignore obsolete responses when selections change.
Frontend caches are UX optimizations, never authorization evidence.

## Styling and reusable contracts

Extract actual Figma typography, color, spacing, radii and elevation into a
small token system; connect it to Tailwind consistently. Tailwind provides
[theme variables](https://tailwindcss.com/docs/theme) for utility-linked design
tokens; confirm syntax against the version selected by the new repository.
Avoid repeated arbitrary values and global CSS overrides of component internals.

Use strict TypeScript, explicit props and typed state unions for mutually
exclusive outcomes. Validate untrusted API data at the adapter boundary;
TypeScript declarations alone do not validate JSON. Keep transport DTOs separate
from reusable table/view models. Preserve column order and duplicate SQL rows;
use column position as well as metadata when labels repeat.

No state manager, component kit, table/chart/editor library, test runner or
auth SDK is selected by this handoff. Choose only what a confirmed interaction
needs, check compatibility, and record the reason. A library must fit the Figma
design and these boundaries rather than dictate either.
