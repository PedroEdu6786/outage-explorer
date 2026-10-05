# Requirements: Data browsing, SQL, and background refresh
> Status: draft · Slug: data-api · Date: 2026-10-04

## Problem statement

Outage Explorer needs to make its stored national, facility, and generator
observations available to the frontend. Users need to browse tables and submit
their own analytical SQL. Admins need to update all three datasets without
waiting on a long-running browser request or stopping other users' exploration.

The immediate purpose is to agree the product behavior and endpoint contracts
while authentication and authorization are being built, so frontend and backend
integration have a shared target.

## Target user / context

Viewer browses and queries national data. Analyst and Admin browse and query
all three analytical datasets. Admin also starts refresh and reads its outcomes.
Users share the published data; there are no separate copies seeded per user.
The frontend displays stored observations rather than fetching source data or
storage objects directly.

## Success criteria

Users can discover their available tables, browse their records, and submit SQL
against permitted data. Moving between query pages preserves the same result.
Admins can start a refresh covering all three datasets, leave the page, and
later see whether updated data became available. Existing data remains usable
throughout refresh and after failures.

## Acceptance criteria

- The catalog lists only the datasets and columns the signed-in user may access.
- The Explorer can display national, facility, and generator tables according
  to the user's role. Viewer has national-only access.
- Initial browsing supports date-range filters and bounded pages that stay on
  the originally selected version of the data.
- Users submit their own supported read-only SQL from the frontend editor.
- Users select numbered SQL result pages through the same query endpoint.
  Later pages preserve the original execution, including duplicate rows,
  ordering, and any limits explicitly included in the SQL.
- SQL result pages show 100 rows by default and allow up to 500 rows per page.
- A completed SQL result remains available for paging for 15 minutes; later
  requests require an explicit new execution.
- Empty results, truncated results, access denial, busy execution, and expired
  or lost pagination state are distinguishable to the frontend.
- Each refresh attempts national, facilities, and generators together.
- Admin starts refresh using the configured date range, without choosing dates
  per request. The run's outcome shows the range actually used.
- Refresh runs in the background and continues after a browser disconnect.
- Admin can inspect progress and a final outcome, including validation
  exclusions, retained older records, failures, and whether data was published.
- A complete verified generation becomes active automatically. Failure keeps
  previously published data available; existing pagination stays on its version.
- Older valid records survive invalid replacements or absent source keys.
  Entirely excluded incoming datasets retain their prior data while valid
  updates from other datasets may publish. If all three are entirely excluded,
  the outcome states that no new generation was published.
- Initial publication requires usable data in all three datasets. Data stored
  successfully without publication is not presented as active.
- Authorization applies to direct requests and every continuation page.

## Non-goals

- User registration, user-management endpoints, or seeding users through HTTP.
- Separate refresh actions for individual datasets or user-specific data copies.
- Facility and generator identifier filters in initial table browsing.
- SQL writes, operational-user/session-table queries, arbitrary files, or
  user-selected external data sources.
- Separate publication approval, scheduled refresh, or cancellation features.
- Implementing endpoints, frontend screens, deployment, or live data publication
  during this requirements and contract discussion.

## Open questions

Review identified these remaining user-visible choices:

- What should a table show before the user sets dates: all available dates or
  a preset interval, and oldest or newest observations first?
- How should an Admin rediscover an active/recent refresh after returning to
  the app without the original run ID? The current contract only reads a known run.
- Should the prepared national offline-capacity metric be columns of the national
  table or a separate national-derived catalog entry? The metric itself is
  already required; only its presentation is open.

Response encoding, exact errors, retry/recovery behavior and publication-state
representation remain design details in [http-contract.md](http-contract.md).
These questions do not reopen accepted role access, filter scope, SQL page
sizes/lifetime, or configured all-dataset background refresh.

## Grounding

This draft consolidates the current discussion and existing accepted product
policies. New transport details in the companion contract remain proposals.

- [Backend specification](../outage-explorer-backend/spec.md).
- [Connector specification](../data-connector/spec.md).
- [User-access requirements](../user-access/requirements.md).
- [Preview pagination](../../adr/0015-dataset-preview-pagination.md).
- [Numbered SQL pages](../../adr/0021-number-query-result-pages.md).
- [Initial load and retention](../../adr/0037-connector-initial-load-and-retention.md).
- [Configured HTTP refresh range](../../adr/0051-configured-http-refresh-range.md).
