# outage-explorer
Outage Explorer lets users explore locally stored U.S. nuclear outage data,
query datasets their role permits, and understand discrepancies between
national, facility, and generator observations.

The core promises are local availability after ingestion, trust through
reproducible evidence from actual EIA records, and access control that never
exposes facility or generator details to Viewers.

Current repository scope: the data connector, data model, and backend API.
Frontend work is deferred. See [project context](docs/context/overview.md).

Codex session devlogs are configured in `.codex/hooks.json`. Review and trust
the two hooks through `/hooks` to enable them. See
[devlog behavior and tests](docs/context/conventions.md#automatic-codex-devlog).
