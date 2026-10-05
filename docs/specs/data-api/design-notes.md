# Data API: recovery, representation, and resource discussion

Status: **analysis and recommendations**, not an accepted implementation plan.
The user requested discussion of restart behavior and analysis of contracts and
resources. Accepted decisions are identified separately from new proposals.

The [formal specification](spec.md) carries the agreed behavior and marks
unresolved choices; this analysis supplies context for subsequent planning.

## Accepted follow-up decisions

- Browse all available dates by default, newest observations first, with optional
  date filters and stable snapshot pagination.
- Add an Admin latest-run lookup to rediscover an active/recent refresh.
- Include the prepared national metric alongside the reported percentage in
  `national`, without a separate metric dataset.
- Use `succeeded` for confirmed new publication and `retained` when all incoming
  rows are excluded and prior valid data remains active. This matches the
  connector plan's existing terminology.

## Publication uncertainty: recommendation

Use an explicit, nonterminal `publication_unknown` run status and a publication
state enum: `pending`, `published`, `not_published`, `unknown`. These are contract
proposals implementing the existing requirement not to report unconfirmed success.

| Situation | Run status | Publication state |
| --- | --- | --- |
| Admitted or working before confirmed completion | `accepted` / `running` | `pending` |
| New generation durably confirmed | `succeeded` | `published` |
| All incoming rows excluded, previous generation kept | `retained` | `not_published` |
| Failure known to have occurred before publication | `failed` | `not_published` |
| Running worker lost, confirmed unpublished after recovery | `interrupted` | `not_published` |
| Commit outcome cannot yet be established | `publication_unknown` | `unknown` |

For example, losing a connection while committing does not prove rollback.
Keep the run unresolved and reconcile against its durable run and generation
records after reconnecting. A matching publication record proves that run's
success even if another generation has subsequently become active. A source/S3
receipt alone never proves publication.

Do not start another refresh until ownership/publication uncertainty is resolved.
Do not re-ingest or republish automatically to discover whether an earlier commit
worked. A stale worker must not be able to publish after ownership is recovered.
Readers use the last durably confirmed active reference; new reads that cannot
resolve it return unavailable, while already pinned readers may continue.

If PostgreSQL cannot validate the caller or retrieve the outcome, HTTP returns
`503 service_unavailable`; it cannot promise to serve a status object during a
database outage. The frontend preserves its last displayed status and marks
the current status unavailable. Once readable, the status resource reports the
reconciled outcome or explicit remaining uncertainty.

## Restart behavior: accepted direction and proposed mechanics

"Runs in the background" protects the operation from browser and HTTP request
lifetimes. It does not by itself define what a worker or host crash should do.

| Event | Recommended behavior |
| --- | --- |
| Browser closes / session expires | Admitted work continues; inspecting outcome requires current Admin access |
| HTTP API restarts but worker is healthy | Worker continues independently; API reconnects to durable run state |
| Whole service restarts with accepted, unclaimed work | Supervisor claims and runs that recorded request using its frozen configuration |
| Worker/host stops during execution | Fence stale ownership and reconcile publication; if unpublished, mark `interrupted` |
| Worker stopped after a committed publication | Recover `succeeded` from durable records; do not repeat source work |
| Database outage makes commit outcome unknowable | Keep unresolved; resume reconciliation when the database recovers |

The user selected explicit Admin retry for an unpublished interrupted run, after
publication reconciliation; API-only restarts preserve a healthy worker. See
[ADR-0052](../../adr/0052-interrupted-refresh-recovery.md). The proposed retry
uses a new key/run and the current configured interval, exposed in its receipt.
Repeating the old key returns the original interrupted run. Automatic source
restart or partial EIA pagination resumption is not part of this decision.

Even with manual source retry, status reconciliation is automatic. The Admin
should not need to diagnose whether publication committed. Before marking a
running job interrupted, a restarted API must establish that its owner is gone
or expired; API startup alone is not proof of worker failure.

## Public schema and response representation: analysis

The implemented modeled schemas already contain the values below. Propose stable
public relations `national`, `facilities`, and `generators` and avoid exposing
storage-origin structures or object keys. The public projection is narrower than
the evidence artifacts, which remain available for controlled verification.

| Public field | Relations | Proposed API encoding / meaning |
| --- | --- | --- |
| `period` | All | Date string |
| `facility`, `facility_name` | Facilities, generators | Strings |
| `generator` | Generators | String; identity includes facility |
| `capacity_mw`, `outage_mw` | All | Decimal strings, logical `DECIMAL(38,12)`, MW |
| `reported_percentage` | All | Decimal string, logical `DECIMAL(38,12)`, percent |
| `calculated_percentage_rounded` | National | Decimal string, logical `DECIMAL(38,2)`, accepted half-up presentation |
| `percentage_numerator`, `percentage_denominator` | National | Exact ratio components as strings, denominator positive |
| `calculated_percentage_display`, `reported_percentage_display` | National | Existing two-decimal presentation strings |

National metric values derive from the stored national observation. They are
not facility sums. Keep the explicit `rounded` name so a two-decimal result is
not mistaken for the exact ratio. Other modeled evidence/source-string fields
remain stored; this proposal does not discard them. Schema changes should be
versioned and authorized identically in catalog, preview, and SQL.

Use one tabular response convention: ordered column metadata plus arrays of
cell values. It handles SQL aliases with duplicate names without losing data.
Metadata carries a logical type and JSON encoding; `nullable` may be unknown
for an arbitrary SQL expression, and `unit` is null unless reliably known.

Proposed scalar encoding rules:

- Strings, booleans, and nulls use their corresponding JSON values.
- Decimal and integer SQL values use strings, consistently across small and
  large values; pagination counters remain bounded JSON integers. The current
  draft only singled out 64-bit integers; using strings for all SQL integer
  cells avoids width-dependent client behavior.
- Dates/times use documented ISO strings. Preserve timezone-free timestamps
  as timezone-free; normalize timezone-aware instants to UTC. Operational run
  timestamps are UTC.
- Finite floating-point results are JSON numbers. Proposed non-finite values
  are the strings `NaN`, `Infinity`, `-Infinity` under float column metadata,
  rather than invalid JSON or silent null substitution.
- Lists encode recursively; maps use key/value entries so non-string keys are
  preserved. Structs use ordered fields described by recursive type metadata.
  Binary uses base64 with explicit type/encoding metadata. Define bounded depth,
  cell size, and schema size; verify the exact adapter against supported engine
  values before claiming all types are supported. No blanket SQL feature
  restriction follows from an unfinished serializer.

This type vocabulary requires representative adapter tests (duplicate labels,
large integers, exact decimals, temporal values, nested values and a single
oversized row). It does not require the user to select implementation libraries.

### Preview navigation and ordering

Keep accepted cursor pagination for previews. Recommend returning a `page_cursor`
for the current page as well as `next_cursor`; the frontend keeps the visited
cursor stack for Previous. Each cursor reauthorizes and stays on the original
generation, including revisiting page 1. No extra endpoint or numbered random
jump is implied. Discard the stack when filters/page size change or on expiry.

Use `period DESC`, with ascending facility and generator string identifiers as
tie-breakers under a fixed documented comparison. This is display ordering;
source retrieval order and arbitrary SQL ordering retain their own policies.

### Error and retry semantics

Keep `{error: {code, message}}` and the proposed error table as the baseline.
Expose an optional bounded `retry_after_seconds` where retry is meaningful,
in agreement with `Retry-After`. Oversized page-size requests are rejected,
not clamped; an empty SQL result has page 1 with no rows. Page size changes
within an execution are rejected. Lost results require explicit resubmission.

Bound the idempotency key's length/format. Associate it with the local user and
operation, retain it with the durable run, and do not expire it independently
while the run remains discoverable. Same-key retry returns the same run/frozen
interval; a new deliberate refresh uses a fresh key. The HTTP body is empty,
so caller-supplied dates are invalid input, not an idempotency mismatch case.
Exact key syntax and broader run-record retention remain design details.

## Resource limits: analysis and proposed starting point

Already accepted: one analytical worker at a time; 10-second execution deadline;
1,000 rows or 1 MiB total serialized result; SQL page default 100/max 500; fixed
15-minute result lifetime. Page size does not increase the total output cap.

### Retained results

For initial testing, propose up to **3 unexpired results per user and 10 globally**,
including reservations for admitted in-flight SQL. With the accepted 1 MiB cap,
this bounds canonical retained payload to at most 10 MiB, plus separately bounded
indexes/metadata and storage overhead. These are proposed admission defaults,
not measured worker/process memory budgets or accepted production sizing.

- Reserve a slot and worst-case retained-result capacity before execution.
- Do not evict an unexpired result just to admit another query. Return a
  retryable capacity response (`429 result_capacity_exhausted` for per-user
  quota, `503 result_capacity_exhausted` for global quota, proposed).
- Reclaim expired state without waiting for another request; clean orphaned
  private result files after store loss. Query-ID metadata remains ephemeral.
- Release the analytical worker after the bounded result is retained; the
  15-minute paging lifetime must not occupy the execution slot.
- Charge UTF-8 serialized columns, retained rows and fixed result metadata once
  against the full-result byte budget. Bound page-envelope/schema overhead too;
  do not multiply the allowance by page count or omit large column labels/types.
  Freeze exact accounting and one-row-too-large behavior in adapter tests.

The tradeoff of a small result quota is visible: after three quick queries a
user may need to wait for the oldest result to expire. This proposal needs
product acceptance or adjustment. It preserves current page access; an explicit
discard-result action would be additional scope and is not silently introduced.

### Worker, cache, and refresh budgets

Existing connector measurements cannot size DuckDB workloads. The latest recorded
initial-interval GET-only S3 replay is about 93 seconds with about 154 MB peak RSS,
63.4 MB durable graph, and 80.5 MB local graph-plus-derived staging. It includes
raw/evidence dependencies and verification, not just authorized modeled query
inputs. It does not prove analytical cache sizes, query memory, or live refresh
duration. See [resource evidence](../data-connector/resource-evidence.md).

Measure query preparation/cache downloads separately from the 10-second execution
deadline. Measure worker peak memory and spill for scans, sorts, joins, windows,
aggregates, nested results and cold/warm cache; then choose a hard worker ceiling
with an engine budget below it. Keep independently bounded storage for modeled
cache, worker spill, retained results, and connector staging. Include API plus
query plus refresh overlap, including multiple readers retaining older generations.

Do not borrow existing connector logical-buffer settings as enforced OS limits.
Connector budgets are already configured and bounded; verify them under background
supervision. API worker count, launcher, overall/preparation deadline, cache/spill
quotas and production memory remain measurement/design gates. No new numerical
production claims follow from this analysis.

### Proposed refresh persistence improvement

A live refresh showed ongoing S3 activity while its broad `persisting` stage
appeared stalled to the user. The HTTP worker currently selects one persistence
worker despite the connector's existing bounded concurrency support. See the
[refresh persistence improvement](refresh-persistence-improvement.md) for dated
observations, proposed instrumentation and concurrency work, and verification
criteria. It remains a proposal; current runtime defaults and publication gates
are unchanged.
