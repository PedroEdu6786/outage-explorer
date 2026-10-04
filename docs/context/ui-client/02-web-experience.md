# Web experience and Figma implementation

This file defines behavioral expectations. Screen grouping, navigation,
typography and visual composition come from the supplied Figma design, which
has not yet been inspected. Component names below are illustrative.

## Figma workflow

Obtain the file URL and relevant frame/node links. Inspect actual layouts,
components, variants, tokens, fonts, icons, assets and responsive frames.
Build an inventory mapping repeated elements to atoms, molecules, organisms
and templates before writing whole screens.

Preserve the intended hierarchy, spacing, density and interactions. Reuse
tokens and variants across screens. For missing responsive or interaction
states, document the proposed extension rather than claiming it was in Figma.
If Figma conflicts with permissions or accepted data behavior, surface the
specific conflict and propose an adjustment. A mockup cannot grant access or
change SQL semantics. Login visuals may provide the entry to Cognito; do not
turn a designed password form into an unapproved custom authentication flow.

## Authentication and navigation

The initial app can have a sign-in entry, permitted dataset browsing and a SQL
workspace, combined or separated according to Figma. Exact routes are a UI
design choice. National metrics fit the relevant analysis screen. Refresh
controls are conditional on confirmed Admin UI scope.

Use Cognito managed login with Authorization Code + PKCE. The accepted
application session lasts one hour by default; it does not automatically renew.
Session expiry requires explicit sign-in. Current-session logout must invalidate
backend access for that session, while independent sessions remain independent.
Credential failures are generic; callback/configuration failures need actionable
messages without exposing tokens or internal details.

Before identity/capabilities resolve, show a pending state rather than briefly
rendering restricted navigation. On logout, identity change or lost access,
clear protected client data and prevent late responses from restoring it.
Preserve unsent SQL text through ordinary errors where safe, but do not persist
protected results as a way to bypass session checks.

## Catalog and previews

Show only returned authorized datasets and schema metadata. Do not populate
Viewer autocomplete, filters or hidden panels from facility/generator data.
Render schema-driven tables; arbitrary SQL output must not be forced into a
national-record shape. Dates, identifiers, numbers, units and nulls should be
distinguishable. Render source strings as text, never trusted HTML.

Preview filters are applied by the backend. Validate date input and ranges
before requesting data, then respect backend validation. Changes to dataset,
filters or page size start a new browsing sequence. Ignore stale responses
from the previous selection.

Preview pagination defaults to 100 rows, with an initial configurable maximum
of 500. The continuation cursor belongs to the original caller, dataset,
filters, ordering and snapshot. It expires 15 minutes after the first page;
continuation does not renew it. Refresh publication must not mix newer rows
into that sequence. On expiry, explain that browsing must restart and provide
an explicit restart action. Do not invent random page jumps or total pages
when the backend supplies only a continuation cursor.

## SQL workspace

Support an editable SQL statement, authorized schema reference, explicit Run
action, execution status, results and errors. The supported language includes
joins, CTEs, subqueries, aggregates and window functions over authorized data.
An editor library and SQL autocomplete are implementation choices; neither
changes the backend's validation responsibility.

Keep draft SQL separate from the submitted SQL and retained execution. Editing
the draft does not change which execution produced the visible results.
Clearly identify results from the last submitted statement when the draft changes.

SQL pagination is different from previews:

- The first execution uses positive `page` and `page_size`; pages are 1-based.
- Subsequent requests select a page using the opaque `query_id`, without
  resubmitting SQL. Revisiting pages uses the same execution and fixed size.
- Changing the SQL page size requires an explicit new execution; communicate
  that consequence before starting it. SQL defaults/maxima remain undecided.
- Do not inject `ORDER BY`, `LIMIT` or `OFFSET`, deduplicate result rows, or
  sort just the visible page as if the entire query result were sorted.
- Without explicit SQL ordering, the sequence is stable within that execution,
  but no chronological order or identical sequence on rerun is promised.
- Lost or expired execution state requires an explicit rerun with a new ID.
  Never silently return page 1, rerun on focus/reconnect, or retry execution
  through a generic automatic request policy.

The accepted baseline caps the **whole execution** at 1,000 rows or 1 MiB,
with explicit truncation. A page boundary is not truncation. Show truncation
even when the currently displayed page has fewer rows; never imply all matching
source records are present. A user-supplied `LIMIT` limits the whole result.
Do not invent a total matched count from a retained-result count.

Initially only one analytical query executes at a time. Explain retryable busy
responses and let the user retry deliberately. The 10-second backend execution
deadline is not a guaranteed 10-second end-to-end response time; preparation and
network timing are separate. Cancellation is not promised by the current API.

## Refresh behavior if a screen is included

An Admin explicitly starts background refresh and checks its outcome. Closing
the screen does not imply cancellation. Successful verified publication makes
the new generation active automatically; current data remains available while
refresh runs or fails. Existing previews/results remain tied to their snapshot.

Distinguish run failure, publication with exclusions, and completion without
publication because all incoming rows were excluded. Show quality accounting
for received/excluded/duplicate/modeled rows, exclusion reasons and retained
older data when the backend supplies it. Reasons can overlap; their sum is not
the excluded-row count. Retained-invalid, retained-absent and out-of-interval
rows are not freshly retrieved records. Do not invent a progress percentage.

## State and accessibility expectations

| State | Expected response |
| --- | --- |
| Initial loading | Clear pending state and stable layout; no fake rows presented as real |
| No rows match | Empty result with current filter/query context |
| No published data | Explain data unavailability separately from an empty query |
| Permission denied | Remove restricted content; do not retry with broader inputs |
| Session expired | Explain expiry and offer sign-in |
| Preview expired | Offer an explicit new browsing sequence |
| SQL result unavailable | Offer explicit rerun; retain the draft where safe |
| Busy or timed out | Explain the outcome and offer appropriate deliberate retry |
| Network/backend error | Preserve safe input and show recovery without exposing internals |
| Truncated result | Visible explanation of the total-result cap |

Use semantic headings, buttons, links, labels and table headers; keyboard
operation and visible focus; text equivalents for statuses; readable contrast;
and announcements for important asynchronous outcomes. Charts, if in scope,
need an accessible data alternative. On narrow screens, keep filters and actions
usable and contain wide-table overflow without dropping meaningful columns.
