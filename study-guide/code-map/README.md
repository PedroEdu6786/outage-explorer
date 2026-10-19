# outage-explorer-demo interview walkthrough

Open the [backend guide](index.html) or [frontend guide](frontend.html) in your browser.
Each index contains its six modules and a link to switch guides. The twelve module maps work directly
from disk, offline, without starting the API or installing packages. Frontend
Storybook demonstrations open separately at `http://localhost:6006/`.

Each landing page provides its own suggested 15-minute route. Each module has an
overview and focused views, so you can follow an interviewer’s questions instead
of presenting a fixed slide deck.

| Module | What to demonstrate |
| --- | --- |
| [Authentication](auth.html) | Provider identity, single-use login attempts, local sessions and application-owned roles. |
| [Datasets](datasets.html) | Authorization, verified inputs, pinned generations, cursor reads and cleanup. |
| [Queries](queries.html) | Separate SQL inspection, isolated execution, retained output and pagination without reruns. |
| [Refresh endpoints](refresh-http.html) | Admin admission, idempotency, frozen configuration and status reads. |
| [Refresh worker](refresh-worker.html) | Independent lifecycle, committed claims, lease renewal and recovery. |
| [Refresh execution](refresh-execution.html) | Restore, model, verify, persist three files and atomically publish. |
| [Atomic Design](frontend-architecture.html) | Plain-language definitions and familiar examples of atoms, molecules, organisms, templates and pages. |
| [Frontend Authentication](frontend-auth.html) | Sign-in screen, main action and feedback message. |
| [Frontend Overview](frontend-overview.html) | Dashboard, date filter, summary cards, trend chart and daily table. |
| [Frontend Dataset Explorer](frontend-explorer.html) | Dataset list, filters, preview table and schema tab. |
| [Frontend SQL Workspace](frontend-queries.html) | Schema browser, SQL editor, status message and results table. |
| [Frontend Admin Refresh](frontend-refresh.html) | Refresh buttons and progress message within Overview. |

Frontend modules focus on main screens and visible UI components. Optional code
views show only those pages and components. Each includes a short presentation checklist and links to relevant local
Storybook stories. These are synthetic fixture demonstrations, not live backend
evidence. **Admin Refresh has no dedicated story**: its linked Overview story uses
an Analyst fixture and demonstrates only the surrounding layout. The refresh
walkthrough links directly to its actual implementation.

To run Storybook, use `npm run storybook` in the `outage-explorer-web` checkout
(with its dependencies installed). The default port is 6006. Storybook is not
embedded or loaded automatically by this offline guide.

Frontend feature modules open on **Page & components**, with the main screen above
its visible components. Storybook demonstrations follow the component map.
Admin Refresh is presented as a section of Overview.

## Present the actual code

Backend modules open on **High-level diagram**, a full-width, code-free explanation
with named participants, directional arrows, separate request/lifecycle paths and
failure or ownership boundaries. No source panel, filenames, methods or editor
controls appear in that view. Start with the system behavior, then trace its
implementation in this repository.

1. Choose a module and explain its high-level diagram. **Click any diagram box**
   to open the exact implementing symbol with the **Code** tab selected. Boxes
   are keyboard-accessible links; browser Back returns to the diagram, including
   after cross-module navigation. **Trace this flow in code** opens the whole flow.
2. **Walkthrough** explains its responsibility and failure paths. Related types
   and implementation links let you drill down and return to the diagram.
3. **Code** shows the actual source excerpt with original line numbers and syntax
   highlighting. **Full source** opens the entire embedded file at that symbol.
4. **Open in VS Code** opens the local checkout at that file and line. Cursor is
   also available in the editor selector. The browser may ask to launch the
   installed editor; the source viewer works independently of that handler.
5. Use **Backend modules** or **Frontend modules**, the module selector, or explicit cross-module links
   to travel between flows. The URL fragment preserves the view, symbol and tab
   across reloads and supports bookmarks.

The header’s **High-level diagram** button returns to the conceptual view from
any implementation view. All high-level views use `#high-level` bookmarks;
existing code-view bookmarks retain their original destinations. For external
participants such as Cognito, a box opens the demo’s integration boundary; its
description explains which side is implemented here.

**Project path** changes the local checkout path for editor links on the current
page. Rebuild after moving the checkout to set the default path on every page.
**Copy location** copies the file/line, with a visible fallback if clipboard
access is unavailable.

Diagrams show a reading order through nested calls, not a claim that every
adjacent box calls the next one. The application returns from adapters and
branches according to the selected step’s notes. Type examples are illustrative
and explicitly identify partial shapes; they are not captured runtime objects.

## Keep source snapshots current

From this repository’s root, using Python 3.12 or newer and Node.js. Rebuilding
frontend snapshots also requires the frontend checkout with its TypeScript
dependency installed; viewing already-built pages does not:

```sh
.venv/bin/python study-guide/code-map/build.py
.venv/bin/python study-guide/code-map/build.py --check
# If the frontend checkout is elsewhere:
.venv/bin/python study-guide/code-map/build.py --frontend-root /path/to/outage-explorer-web
```

The builder parses Python with its AST and TS/TSX with the frontend's installed
TypeScript compiler through `resolve-typescript.cjs`, without importing or starting
either application. It resolves exact symbol line ranges (including Python decorators), verifies
diagram/type/helper/handoff references and their reachability, and embeds only
explicitly referenced product source files. Each module displays a source
fingerprint. All references validate before any generated page is replaced.

`--check` exits unsuccessfully if a page is missing or differs from what the
current source, descriptions and templates would generate. Embedded source is a
build-time snapshot; editor links open the current file. Rebuild before the
interview, including after uncommitted source edits. Recheck the narrative when
behavior changes: resolving a symbol does not prove its description is accurate.

Maintain the twelve module JSON files and the three HTML templates; do not edit generated
`index.html`, `frontend.html` or module HTML files.
`build.py` is the reproducible generator. No runtime dependency was added.

## Source roots

Backend diagrams, source snapshots and default editor links refer to this demo repository.
The generator reads the working-tree files under this checkout’s
`src/outage_explorer/` directory. That directory is the Python package name used
by outage-explorer-demo.

Frontend modules explicitly use `outage-explorer-web/src/`, defaulting to the sibling
checkout. Their embedded snapshots and editor links use that frontend root.
The module selector lists only modules in the current guide; the header links to
the other guide. Explicit frontend-to-backend code handoffs remain available. No backend
source is read from another checkout. Both source trees are confined and references
are resolved structurally; an absent or ambiguous symbol fails the build.

- `PreviewService.page` contains the first read, continuation, response sizing
  and cleanup.
- `QueryService.execute` and `.page` implement execution and retained paging.
- `CognitoIdentityProvider` owns redirect construction and token verification.
- `PostgresqlResourcePublicationStore` owns admission, coordination, recovery
  and publication. `RefreshExecution.execute` orchestrates the pipeline.
- Concrete construction remains in `bootstrap.py`. These navigable modules are
  interview topics within the accepted layered monolith, not separate services.

The artifact contains 57 views (twelve high-level overviews plus 45 implementation
views) and 153 source references across twelve modules.
Source-linked documentation does not establish runtime
authorization, isolation, capacity or deployment acceptance; use the current
specifications and ADRs for those statuses.
