# Data API integration decision tracker

Recorded: 2026-10-05. Scope: contract accuracy and frontend integration.

The contracts are detailed enough to guide integration. The three backend
documentation inconsistencies below require targeted corrections; they do not
invalidate the API. Correction work is pending. Existing frontend assumption
differences are tracked separately and have not yet been enumerated.

| ID | Topic | Agreed direction | Status | Closure evidence |
| --- | --- | --- | --- | --- |
| API-D01 | Missing invalid-parameter responses | Add `400` / `invalid_request` responses to the OpenAPI definitions for `GET /api/datasets` and `GET /api/refresh/latest`, matching the HTTP contract's parameter rejection rules. | Correction pending | OpenAPI and HTTP descriptions agree; contract checks cover both response definitions. |
| API-D02 | SQL example column mismatch | Keep example SQL and response metadata consistent. For SQL naming columns `x, x_copy`, return `x, x_copy`; preserve separate, internally consistent coverage for duplicate column labels. | Correction pending | Related first/direct/revisited-page examples agree on ordered columns and retained execution identity. |
| API-D03 | Row-limit fixture | Resolve the `query_row_limit` example's claim of reaching the 1,000-row cap while reporting two retained rows. Clarify whether it is abbreviated, or supply consistent counters/data. | Clarification and correction pending | Document the selected interpretation. Executable fixture counters and truncation claims remain internally consistent; displayed page length is distinguished from total retained rows. |
| UI-D01 | Existing frontend assumptions | Record each concrete frontend/backend difference separately, with the current assumption, contract behavior, selected resolution and affected client/tests. | Open: differences not supplied | Enumerated differences and explicit resolutions; no frontend assumptions inferred from the backend documentation issues. |

References: [HTTP contract](http-contract.md), [OpenAPI](openapi.json),
[synthetic fixtures](fixtures.json), and [client handoff](client-handoff.md).

Tracking an agreed correction does not mean it has been applied or verified.
Close each item only when its closure evidence is recorded.
