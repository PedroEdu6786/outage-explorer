# Data API integration decision tracker

Recorded: 2026-10-05. Scope: contract accuracy and frontend integration.

The contracts are detailed enough to guide integration. The three backend
documentation inconsistencies below require targeted corrections; they do not
invalidate the API. The targeted corrections are implemented and contract-tested in Phase 6. Existing frontend assumption
differences are tracked separately and have not yet been enumerated.

| ID | Topic | Agreed direction | Status | Closure evidence |
| --- | --- | --- | --- | --- |
| API-D01 | Missing invalid-parameter responses | Add `400` / `invalid_request` responses to the OpenAPI definitions for `GET /api/datasets` and `GET /api/refresh/latest`, matching the HTTP contract's parameter rejection rules. | Closed in Phase 6 | Both GET operations now define 400/Error400; named fixtures and HTTP strict-parameter tests cover invalid input. |
| API-D02 | SQL example column mismatch | Keep example SQL and response metadata consistent. For SQL naming columns `x, x_copy`, return `x, x_copy`; preserve separate, internally consistent coverage for duplicate column labels. | Closed in Phase 6 | First/direct/second/revisit metadata uses x,x_copy consistently; query_duplicate_labels independently uses x,x. Contract checks preserve identity and ordered columns. |
| API-D03 | Row-limit fixture | Resolve the `query_row_limit` example's claim of reaching the 1,000-row cap while reporting two retained rows. Clarify whether it is abbreviated, or supply consistent counters/data. | Closed in Phase 6 | Complete one-row page 1 represents 1,000 retained rows and 1,000 total pages; counters and max_rows agree. No abbreviated result claims. |
| API-D04 | Reference-free SQL and internal encoding metadata | A reference-free expression returns nullable generation_id because it reads no publication. Keep internal encoding_version in the spool only. | Closed in Phase 6 | HTTP response validates the updated nullable schema and exact property allowlist; separate reference-free fixture included. |
| UI-D01 | Existing frontend assumptions | Record each concrete frontend/backend difference separately, with the current assumption, contract behavior, selected resolution and affected client/tests. | Open: differences not supplied | Enumerated differences and explicit resolutions; no frontend assumptions inferred from the backend documentation issues. |

References: [HTTP contract](http-contract.md), [OpenAPI](openapi.json),
[synthetic fixtures](fixtures.json), and [client handoff](client-handoff.md).

Tracking an agreed correction does not mean it has been applied or verified.
Close each item only when its closure evidence is recorded.
