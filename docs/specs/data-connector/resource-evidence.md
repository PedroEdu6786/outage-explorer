# Connector resource evidence

Measured October 4, 2026 on the local macOS/Python environment recorded in
[measurements](evidence/2026-10-04/measurements.json). These are contributor
pipeline measurements, not production budgets or hard process isolation proofs.

## Sequential baseline and placement

The controlled 30-day input contains one observation per date per grain, page
length 5, identical input values and a synthetic secret. Fresh subprocesses
measure full source collection, Parquet writes/modeling, repeated verification
and reopened replay. They do not model real HTTP latency. The baseline preceded
concurrency implementation.

| Full candidate pipeline | Workers | Seconds | Process peak RSS bytes | Local bytes |
| --- | ---: | ---: | ---: | ---: |
| Controlled 30 days | 1 | 5.163 | 106,692,608 | 2,273,378 |
| Controlled 30 days | 3 | 5.186 | 101,711,872 | 2,273,665 |
| Live one day | 1 | 14.617 | 109,674,496 | 792,054 |
| Live September | 1 | 41.389 | 107,905,024 | 12,173,312 |
| Live exact-prior one-day rerun | 3 | 11.269 | 108,724,224 | 1,645,655 |
| Initial interval diagnostic (incomplete) | 3 | 564.433 | 110,788,608 | 74,229,991 |

RSS is macOS `ru_maxrss`, a process-lifetime high-water mark including Python,
Arrow, SDK and allocator overhead. Disk totals include local reports and immutable
objects at completion/interruption; they are not sampled peak temporary usage.
Rerun inputs can drift and are not an identical-recorded-input timing comparison.
Arithmetic and per-date modeling use the existing exact decimal/fraction policies;
no new arithmetic limit has been established by these runs. Per-day incoming/prior,
output, digit/exponent and file/batch caps remain explicit caller limits.

Choose bounded threads for independent I/O/evidence collection and SDK transfers.
Modeling/replay, combined manifests, reports and final receipt gates remain
coordinator-owned. The controlled pipeline did not become faster with three
endpoint workers; no CPU speedup is promised. A process executor would add
serialization/ownership complexity without a measured benefit here. Page order
and source positions stay local to each endpoint.

## Transfer baseline and comparisons

The controlled graph contains 310 immutable objects and 1,925,323 graph bytes.
Every operation verifies/replays the graph, including fresh readback. Retry means
conditional writes encountering identical existing bytes.

| Controlled SDK operation | Sequential seconds | Three-worker seconds |
| --- | ---: | ---: |
| New graph upload + readback/replay | 5.247 | 5.093 |
| Identical-object retry + readback/replay | 5.544 | 5.059 |
| Empty-staging recovery/replay | 3.918 | 3.449 |

Sequential peak RSS reached 102,531,072 bytes; concurrent peak reached
102,891,520 bytes. Within each transfer subprocess those are cumulative high-water
marks, not isolated peaks for each operation. A native fake SDK has no meaningful
network latency, so these modest differences are descriptive.

Actual one-day S3 graph: 75 objects/687,569 bytes. Sequential new upload/readback
21.958 seconds; concurrent identical-object retry/readback 8.154 seconds. Those
upload states differ and do not establish a fair upload speedup. Empty-staging
recovery of the identical graph was 6.256 seconds sequential and 2.825 concurrent.
Inherited graph: 150 objects/1,438,271 bytes; parallel persistence/readback
19.276 seconds, peak RSS 152,977,408 bytes. Recovery evidence is recorded separately.

## Supported settings and aggregate enforcement

Typed `workers` defaults retain sequential endpoint/S3 execution (`1` each),
with independently selectable `1`–`3` workers. `memory_bytes` defaults to
512,000,000 logical buffer bytes; `temporary_bytes` to 700,000,000 (raised with the
32,000,000-byte file bound of ADR-0057; initial, unmeasured limits). They bound
admitted payload/file envelopes, not total interpreter/native RSS. Invalid types,
counts above three and insufficient aggregate buffer/staging envelopes fail
before source/client work. Source caps on requests (including retries), pages,
rows, received bytes and sanitized output are shared atomically across endpoints;
worker count never multiplies them. One source/pipeline deadline and cooperative
checks cover transport, evidence, store commits and bounded model/replay batches.

Parquet store commits serialize object-count/byte-accounting updates, while
independent encoding and network reads can overlap. Recovery discovery,
deduplication and conflicting-reference checks stay coordinated. SDK reference,
wire byte, request and temporary-upload accounting uses one shared lock/deadline.
The transfer request cap is 100,000; existing per-object attempts, wire/chunk/time
caps remain explicit. Static staging admission reserves both complete local and
readback graphs plus concurrent file staging within the caller's temporary budget.
These application buffers are distinct from unproven OS process memory/disk limits.

Boto3 low-level clients may be shared between threads with their documented
caveats; sessions/clients are constructed before worker admission, used only in
one process and closed after join. No metadata/event-hook mutation or transfer
manager/multipart behavior is introduced. See the [official client documentation](https://docs.aws.amazon.com/boto3/latest/guide/clients.html).
Default network requests retain finite timeouts; failures cancel admission and
join all worker threads, preserving completed immutable objects. A final root
requires every dependency, and a receipt requires complete graph replay.

The full April 2–October 1 input exceeded the selected 300-second limit. Its
old diagnostic process revealed delayed deadline observation during repeated
synchronous replay; cooperative storage-boundary checks now stop such work. The
183-day interval is not supported by the demonstrated complete-pipeline evidence.
No production worker budgets, enforceable OS launcher, deployed role, service
restart recovery, active generation preservation or publication is established.

## Default revision after the recorded runs

The user requested plain `make connector START=2026-04-02 END=2026-10-01`
without a JSON profile. [ADR-0048](../../adr/0048-initial-interval-connector-defaults.md)
replaces the old small fixture defaults with bounded contributor allowances:
183 days, 500 rows/page, 30,000 source/model rows, 1,800 seconds for candidate
processing and separately for S3 transfer/replay. Artifact storage is 256 MB;
logical buffer/staging admission is 256/600 MB; S3 attempted wire bytes are
1.6 GB. Request timeouts are 10 seconds and source retries allow three attempts.
Existing measurements retain their exact original configurations. The increased
allowances remove configuration rejection; they do not demonstrate completion,
speed improvements, OS enforcement or production support. T6.4/T6.C remain open.


## Page-fetch extension (ADR-0049)

Typed `workers.page_workers` now defaults1 and accepts1–3; explicit
`--fetch-workers`/Make `FETCH_WORKERS` override it. Endpoint and S3 worker settings
retain their existing defaults/compatibility. Current contributor allowances are
ADR-0048's183-day/1,800-second settings, not the earlier measurement profiles.
No old measurement is replaced and no full183-day live run was executed here.

Controlled single-route barriers prove three concurrent page requests and reverse
completion. Canonical replay/equivalence, short-page offset repair, unused audit
counts, exact source-disabled S3 reconstruction, retained origins, shared fetched
row exhaustion, failures/interruption and nested worker cleanup are covered by
`test_eia_page_concurrency.py`. Supplemental JSON values are hash/byte checked,
linked to exact graph manifests and verified against canonical request identity,
parameters/time/offset/count and every raw value. Rehashed inconsistent audit
values fail. Replay retains only the current window of up to three responses.

All admitted requests consume shared request/bytes/pages/rows limits, even unused
lookahead. Sanitization traversal counters/path lists are function-local; per-route
request/read counters use narrow locks. Logical buffer admission multiplies
endpoint*page workers, and transports close after all nested workers join. The
shared HTTPX pool uses HTTPCore's documented thread safety ([official documentation](https://www.encode.io/httpcore/connection-pools/)).
No source snapshot/recency, faster model processing or new production budget is
claimed. The existing full initial verification gate remains open.

## October 4 comparison-stage replay correction (ADR-0050)

The interrupted run `95eb8ba9fa14407cb8d63ef543a4c637` had retrieved all
183/10,065/17,385 canonical rows and had no confirmed manifest. Verification
previously decoded complete raw evidence separately for every day, including
malformed-date disposition partition, and again during retained-origin binding.
Fresh replay-derived immutable day indexes now preserve the same exact checks.
Derived objects share store accounting and are excluded from the durable graph.
Recovery therefore requires bounded local space for graph plus derived staging;
existing aggregate store/worker admission remains fail-closed.

Controlled identical183-day inputs (one valid row per day per grain) passed both
old unindexed and new indexed exact verification: **552 versus3** day-index raw
replays; **8.810 versus1.808 seconds**. Thirty days: **93 versus3** replays;
**0.669 versus0.316 seconds**. Version/evidence validation passes remain in both
algorithms and are separate from these counts. Tests assert counts independently
of duration, compare exact artifact verification, and verify retained original
origins with six replays for current+inherited three-grain evidence.

Source-disabled local reconstruction from the interrupted run's captured live
page/raw/audit objects, with normal hash/schema/link/replay checks and default
budgets, succeeded in fresh staging. Copy+evidence validation1.406 seconds;
build including full verification20.995 seconds; separate fresh verification
11.075 seconds; total33.476 seconds. Peak process RSS62,128,128 bytes; local
2,857 objects/80,516,264 bytes. All183/10,065/17,385 rows were selected and all
three grains had183 usable dates. This measured local reproduction does not prove
future source stability, fresh CLI completion or configured-bucket durability.
Original partials/report were preserved; no EIA/AWS request or write occurred.

## Final initial-interval configured-S3 measurement

The fresh live candidate `de9648fcb92149a98d66aba51e4f667f` verified183 usable dates
per grain with183/10,065/17,385 selected observations. Separate GET-only CLI
recovery of its exact durable graph, EIA disabled and3 S3 workers, took93.154seconds:
2054 durable objects/63,420,955bytes, peakRSS154,238,976bytes, local graph-plus-derived
staging2857objects/80,516,102bytes. Full semantic replay and equality to local
summaries passed. See [tracked raw measurement](evidence/2026-10-04/initial-interval-recovery.json).
This is one concrete initial-interval and cloud-recovery measurement, not a new
production/default-budget guarantee. Source retrieval duration for this user-run
candidate was not separately measured. Earlier failed/replay-only measurements
remain historical evidence; the six-phase connector completion gate is now closed.
