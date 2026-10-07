# Connector operations

[Back to README](../../README.md)

Run these commands from the backend checkout after `make setup`.
The connector reads `EIA_API_KEY` from the process environment. Unlike Flask,
it does not automatically load `.env`.

## Extract and verify

Export your EIA key privately. For default S3 persistence, also configure
`AWS_PROFILE` or runtime credentials, `AWS_REGION`, `OUTAGE_S3_BUCKET` and
`OUTAGE_S3_PREFIX` in the command environment.

```sh
make connector-help
make connector START=2026-09-01 END=2026-09-01
```

Default success requires complete durable readback of exactly three resource
Parquet files. To build an AWS-independent candidate explicitly:

```sh
make connector LOCAL_ONLY=1 START=2026-09-01 END=2026-09-01
```

Optional JSON configuration and explicit overrides:

```sh
make connector CONFIG=connector.config.example.json
make connector CONFIG=connector.config.example.json END=2026-09-01 STAGING=data/connector-one-day
make connector START=2026-04-02 END=2026-10-01 FETCH_WORKERS=3 S3_WORKERS=3
```

See the [configuration example](../../connector.config.example.json).
Precedence is explicit flags, JSON fields, then typed defaults. The key stays
in the environment. Limits are bounded contributor settings, not measured
production capacity. Page/endpoint workers default to one; S3 workers default
to three. Concurrent pages are consumed in canonical source order.

EIA requests default to a 30-second timeout per network phase and five total
attempts per request (including the first). Retry delays use a 10-second base
with exponential backoff and jitter: 5–10, 10–20, 20–40 and 40–80 seconds
before the four retries. The backoff cap is 120 seconds, including accepted
`Retry-After` seconds or HTTP dates; larger server delays fail the run rather
than retrying early. A `429`, or a retryable response carrying `Retry-After`,
pauses new requests across all source workers in the run. Other transient
failures back off the affected request. Logs include the chosen delay and
whether the cooldown is shared, without retaining response headers.

All metadata, page and retry attempts share a limiter that spaces admissions
at least 1,000 milliseconds apart (about 3,600/hour). Idle time does not accumulate
burst credit. Endpoint/page concurrency can overlap in-flight requests but does
not multiply this allowance. Both pacing and retries check cancellation at most
every 100 milliseconds while sleeping and count against the retrieval deadline.
The default overall retrieval allowance remains 1,800 seconds; its remaining
time can shorten network timeouts or prevent further requests. Other resource
limits still apply.

The [EIA FAQ](https://www.eia.gov/opendata/faqs.php), checked October 7, 2026,
advises staying below roughly 9,000 requests/hour and bursts below 5/second under
ideal conditions. Actual throttling also considers API-key use, IP traffic and
series demand, with tighter restrictions possible on complex routes. Exact
firewall rules are not public; temporary bans can last seconds or minutes.
Our defaults provide headroom, not a guarantee against throttling. The limiter
is shared within one run, not across independent processes or other consumers
using the same key/IP.

These defaults apply to the independent HTTP refresh worker after restart.
Connector JSON `source` overrides can tune `attempts`, `timeout_seconds`,
`backoff_base_seconds`, `backoff_seconds`, and `request_interval_milliseconds`
independently; all must be positive integers. For example:

```json
{
  "source": {
    "backoff_base_seconds": 10,
    "backoff_seconds": 120,
    "request_interval_milliseconds": 1000
  }
}
```

## Safe reruns, persistence and recovery

Use a prior verified local report from the same staging store for merge/retention:

```sh
make connector START=2026-09-01 END=2026-09-02 STAGING=data/connector-local PRIOR=data/connector-local/runs/RUN_ID/report.json
```

Identical observations collapse, valid revisions replace older values, and
invalid replacements or absent keys retain prior valid observations. An
all-excluded refresh keeps the previous data. Source evidence and quality counts
make exclusions and retention explicit.

Preserve the local report, three referenced resource files and durable receipt
for explicit source-disabled retries or recovery:

```sh
make connector OPERATION=persist STAGING=data/connector-local RESOURCES=data/connector-local/runs/RUN_ID/report.json
make connector OPERATION=recover STAGING=data/connector-recovered RESOURCES=data/connector-local/receipts/GENERATION_ID.json
```

Recovery requires absent or empty staging and needs no EIA key. Durable files use
`<prefix>generations/<generation-id>/{national,facilities,generators}.parquet`.
Identical S3 retries verify existing bytes; conflicts fail without overwriting.
There is no remote manifest discovery or automatic pruning. A verified candidate
or durable receipt is not a published application generation.

## Failure behavior

| Condition | Behavior |
| --- | --- |
| Missing EIA key, invalid configuration or missing S3 target | Exit 2 before source work |
| EIA rejects credentials (`401`/`403`) | Fail without retrying the rejected request; no publication |
| Transient network failures, `429` or `5xx` | Retry with bounded backoff and `Retry-After` handling; fail when attempts, requests or retrieval deadline are exhausted |
| Malformed responses or failed pages | Fail instead of accepting partial retrieval |
| Invalid source rows | Exclude with visible reasons; preserve prior valid replacements where applicable |
| No usable initial output in any grain | Fail initial loading; do not confirm a candidate |
| All incoming rows excluded on a rerun | Retain the prior candidate and report `retained_all_excluded`; exit 0 |
| Facility advertised-total discrepancy | Preserve diagnostic; do not use it alone to determine pagination completeness |
| S3 failure or conflicting object | Nonzero exit; preserve local candidate for explicit persistence retry; no local-only fallback |
| Interrupted execution | No publication; cooperative interruption exits 130 |

Verified candidates and all-excluded retention exit 0; runtime failures exit 1.
Logs go to stderr and final status/report paths to stdout. Credentials, request
URLs and raw exceptions are excluded. Report-write failure is a failed run even
if some files were already written. See [logging](../specs/data-connector/logging.md)
and [troubleshooting](../specs/data-connector/troubleshooting.md).

## Product refresh worker

Product refresh is admitted through the Admin-only API and runs independently:

```sh
make run-worker
```

This wrapper loads local `.env`, uses `OUTAGE_ACCESS_DATABASE_*`, `EIA_API_KEY`,
S3 configuration and private `OUTAGE_REFRESH_STAGING` (default
`data/refresh-local`). It claims only admitted runs. Start it only when refresh
processing is intended; ordinary browsing works with refresh idle.

The HTTP API uses configured `OUTAGE_REFRESH_START_DATE` through today's UTC date,
resolved and frozen at each new admission; callers cannot override dates. There
is no 183-day ceiling for subsequent HTTP refreshes. Source/model interval budgets
use that saved inclusive span, while finite row, page, request, byte, memory and
time budgets still apply. Large ranges can fail those budgets without publication.
Update the start and restart the API to narrow the range if needed. Remove obsolete
`OUTAGE_REFRESH_END_DATE`, `OUTAGE_REFRESH_MAX_INTERVAL_DAYS`,
`OUTAGE_REFRESH_SOURCE_INTERVAL_DAYS` and `OUTAGE_REFRESH_MODEL_INTERVAL_DAYS`
settings; HTTP refresh ignores them. Today's observations may not yet be published
by EIA. Initial loading retains its explicit April 2–October 1, 2026 interval;
the connector CLI still uses explicit dates and its configurable resource profile.
See [ADR-0063](../adr/0063-configured-start-current-end-refresh.md).

Complete three-file readback precedes
fenced PostgreSQL publication. Worker loss is reconciled; unpublished interrupted
runs require explicit Admin retry. The API never starts this worker itself.

See the [connector specification](../specs/data-connector/spec.md),
[refresh persistence checkpoints](../specs/refresh-persistence/tasks.md) and
[HTTP contract](../specs/data-api/http-contract.md) for exact behavior and evidence.
