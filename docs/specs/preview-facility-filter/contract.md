# Preview facility-filter contract

Status: **implemented and verified for portable backend scope; runtime evidence gaps remain**.
Phase 3 carries the field through HTTP, application sequences and isolated worker
protocol version 2, with public catalog/OpenAPI updates. Running services need a
matching rebuilt/reviewed worker image and runtime identity; no deployment or
activation is implied. The examples in [contract-cases.json](contract-cases.json)
are synthetic contract cases, not recorded HTTP responses. See the
[specification](spec.md) and [tasks](tasks.md) for scoped verification.

## Initial request

`GET /api/datasets/{dataset}/preview` accepts one optional `facility` query
parameter for `facilities` and `generators`. Analyst/Admin authorization remains
required before analytical access. National preview rejects the parameter,
including an empty value; Viewer cannot use it to access detail datasets.

Facility is an opaque string of **1–256 UTF-8 bytes**, preserving case, leading
zeros, alphanumeric identity, quotes and ordinary internal spaces. The bound is
an application resource limit, not a measured EIA identifier limit. Reject
non-string values, empty values, surrounding Unicode whitespace, Unicode Cc
controls (U+0000–001F and U+007F–009F), malformed Unicode/invalid UTF-8 and values
over the byte bound. Never trim, normalize, numerically coerce or interpret the
identifier as SQL, a wildcard or a substring. One exact equality predicate uses
a bound value on the trusted public facility column in the isolated worker.
Lists and repeated `facility` parameters are invalid, even when repeated values
are equal. Facility names, discovery and generator-specific filters are excluded.

An omitted facility retains existing unfiltered/date-only behavior. A valid ID
with no observations returns a normal empty preview, without an existence lookup.
Optional inclusive `start_date`/`end_date` intersect with facility selection;
omitted date sides remain unbounded within stored coverage. Existing date and
page-size validation and error envelopes apply. Invalid facility input, national
filtering and repeated parameters return `400 invalid_request` after applicable
authorization. Quotes and SQL-shaped text are valid identity data, never commands.

## Continuation and capabilities

The initial sequence freezes facility, dates, page size, owner and generation.
Continuations accept only `cursor`; combining cursor with any filter or page
size returns `400 invalid_request`. Filter changes require a new sequence.
Ordering, revisits, fixed 60-second expiry, authorization on every page and
cleanup/pin bounds remain unchanged. A new publication cannot change an existing
sequence's selected data or facility.

The catalog `supported_filters` arrays, in order, are:

| Dataset | Supported filters |
| --- | --- |
| `national` | `start_date`, `end_date` |
| `facilities` | `start_date`, `end_date`, `facility` |
| `generators` | `start_date`, `end_date`, `facility` |

Strict consumers expecting exactly two date filters may reject the expanded
catalog. This backend feature documents that compatibility impact; implementation
and acceptance do not depend on changes to the separate web project.

## Example scope

The JSON examples retain their original proposed-outcome labels and identifier
validity; they are not runtime evidence.
The pure validator proves only identifier validity: it cannot establish dataset
support, duplicate rejection, authorization, cursor rules, date intersection,
empty-result execution or HTTP status. Phase checkpoints separately record
behavioral tests. AC1–AC6 evidence and remaining database/actual-host gaps are recorded in
[verification.md](verification.md).
