# Data API v1 client handoff

Track pending contract corrections and frontend assumption differences in the
[integration decision tracker](integration-decisions.md).

The web client can implement fixture adapters using [openapi.json](openapi.json)
and [fixtures.json](fixtures.json). Copy both files into the client repository;
neither depends on backend Python. All seven operations have schemas and
synthetic examples. **Data/refresh endpoints are still pending.** Auth remains
governed by the [existing transport contract](../user-access/http-contract.md).

`fixtures.json` contains named request/response cases with operation ID, status,
headers, schema name and body. Catalogs cover Viewer, Analyst and Admin; previews
cover all grains, empty results, continuation and revisits. SQL covers direct and
revisited numbered pages, duplicate labels, empty versus truncated output, exact
large integers/decimals, nulls, nonfinite floats, timestamps, binary and nested
values. Refresh covers every run/publication state, unknown quality and no latest
run. Error fixtures include 429 user capacity and 503 global capacity.

- Keep row arrays aligned with ordered `columns`; never key cells by label.
  Labels may repeat. Render integers/decimals as strings without JavaScript
  `Number` conversion. Precision and scale are in decimal column metadata.
  Recursive `children` describe list elements, struct fields and map keys/values.
- `generation_id` identifies published data. `query_id` identifies one owned
  retained execution; it is not a generation, and GET paging never resubmits SQL.
  Page/page_size belong in URL parameters. POST body contains only `sql`.
- `page_cursor` revisits a preview page; `next_cursor` advances. Send cursor alone
  on continuation. Previous navigation reuses visited cursors. Filters and page
  size changes explicitly begin a new sequence. Dates are inclusive and an
  omitted date side is unbounded within stored coverage.
- Empty rows differ from unavailable data and from a byte-truncated first row.
  `has_more` concerns retained pages; `truncated` concerns total query output.
  Fixed expiry is 15 minutes. A 404/410 continuation requires explicit restart;
  do not silently execute again. Initial `page_out_of_range` can include owned
  `query_id`/`expires_at` in error details for GET recovery.
- Use current session cookies and the existing Origin/CSRF transport. Production
  cookie is `__Host-outage_session`; explicit local HTTP mode uses
  `outage_session`. Auth/origin/CSRF denial is generic `forbidden`. Do not infer
  authorization from a cached catalog or role display.
- Refresh body is `{}` and `Idempotency-Key` is 16–128 ASCII letters/digits,
  hyphen or underscore. Preserve the key when retrying uncertain admission.
  Explicit Admin retry after terminal interruption uses a new key. Backend
  settings choose dates; use the returned effective interval.
- Read `Retry-After` as a retry suggestion, not a completion estimate. Refresh
  admission returns Location/Retry-After; browser CORS integration must expose
  them. All successes/errors use no-store. `publication_unknown` is nonterminal;
  do not label it failure or offer automatic source reruns.

The schemas validate wire structure and type/encoding combinations. Tests also
check projection/nullability parity, page identity, refresh state mapping and
quality conservation. JSON Schema alone cannot establish authorization,
publication, cursor binding or SQL isolation. See [runtime evidence](runtime-evidence.md).
