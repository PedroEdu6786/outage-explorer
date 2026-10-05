# Controlled live connector verification

October 4, 2026. Contributor candidates only; no product activation or PostgreSQL
refresh records. The user authorized bounded EIA reads and then configured-bucket
persistence/reconstruction. The initial-interval connector gate is now closed by
the completed live candidate and exact configured-S3 recovery recorded below.

## Reproduce a bounded run

Provide `EIA_API_KEY` through the environment, never command arguments/configuration.
The application does not load `.env`. Select explicit dates, a fresh staging
location and a JSON configuration; use `--local-only` until cloud writes are
separately authorized. Start with one endpoint worker and small pages. Preserve
run reports and exact manifests before expanding the interval. For example:

```sh
make connector LOCAL_ONLY=1 START=2026-09-01 END=2026-09-01 \
  STAGING=/private/tmp/connector-proof CONFIG=path/to/safe-config.json
```

The one-day configuration used page length 5, at most 200 aggregate pages/400
aggregate requests, 120 seconds and 10-second request timeouts. Other typed limits
retained their defaults. Subsequent 30-day bounds and failed initial-interval
bounds are recorded exactly in [measurements](evidence/2026-10-04/measurements.json).
Use `workers.endpoint_workers: 1` or `3` for sequential/concurrent comparison.
Pages remain sequential within an endpoint; completion order cannot choose winners.

## Actual observations

| Input | Execution | Outcome | Seconds | Received national/facility/generator |
| --- | --- | --- | ---: | --- |
| September 1 | Sequential, length 5 | Verified | 14.617 | 1 / 55 / 95 |
| September 1 exact-prior rerun | Three workers, length 5 | Verified | 11.269 | 1 / 55 / 95 |
| September 1–30 | Sequential, length 500 | Verified | 41.389 | 30 / 1,650 / 2,850 |
| April 2–October 1 | Three workers, length 500 | Interrupted during verification; no confirmed manifest | 564.433 | 183 / 10,065 / 17,385 |

The initial attempt failed closed in retrieval after 2.409 seconds; its retry
completed collection but exceeded the explicitly selected 300-second pipeline
budget during repeated modeling/replay. That process started before cooperative
storage-boundary deadline checks were added and was explicitly interrupted; it
returned `interrupted`, never success. Do not infer a verified initial candidate
from its persisted partial files or its three source summaries. Full initial
completion requires further measured processing work or a supported explicit
validation budget; defaults were not enlarged to claim support.

All successful runs used the existing daily route contract and explicitly
requested ascending period/facility-magnitude/generator-text order. The source
adapter validated ordering and terminal empty pages, preserving short-page
observations and recorded source positions. September 1 length-5 offsets were
national 0,1; facility 0,5,…,55; generator 0,5,…,95. September length-500 offsets
were national 0,30; facility 0,500,1000,1500,1650; generator
0,500,1000,1500,2000,2500,2850. Facility advertised 95 for the one-day input and
2,850 for September despite receiving 55/1,650; those discrepancies remain
visible and nonblocking by themselves. Initial facility advertised 17,385 while
receiving 10,065. No failed page is reclassified as ordinary row exclusion.

Observed order does not establish revision recency. No duplicate tie or source
drift was detected by these counts; controlled cross-page A/B/A cases establish
selection semantics. An observed roster is not upstream completeness. Full
post-September candidate contract applicability remains unconfirmed because the
initial candidate never completed verification, even though retrieval succeeded.

## Exact references and reruns

The one-day manifest is
`daea78aca27c24b09ef1809a3ecf3621f4845ce007f7454885be91d8f62c406d:21341`.
The exact-prior parallel rerun is
`4163a962a3bc069cb72ac247a86165b394b05053c0c00d015e7877f564ef7fc4:39913`.
Its explicit prior was the preceding reference, with the same September 1 interval.
The September candidate is
`f69fecf3f44a725cbf21cced6d85f463f0e7aae3ab04de733766b9d6de9488a9:93220`.
Local reports/artifacts remain under `/private/tmp/outage-phase6-evidence/`, with
nonsecret measurements checked into this repository. Temporary local paths are
not durable evidence. The one-day and rerun graphs have separately verified S3
receipts; see [recovery verification](recovery-verification.md).

Controlled tests compare exact observations, source positions, contract/version,
quality and retained origins across reversed completion order. Execution IDs,
request/page IDs, retrieval timestamps and their evidence hashes may differ.
Absent/invalid/partial/all-excluded cases remain injected cases in the existing
rerun suite, not observations claimed from live EIA. No new live regression case
required changes to that suite.

### Source-disabled reconstruction of interrupted full-interval evidence

October4 stall correction validated captured live inputs from run
`95eb8ba9fa14407cb8d63ef543a4c637` in fresh local staging. Untrusted forensic
inventory was accepted only after normal immutable hash/schema/page-link and
semantic checks. It produced a locally verified candidate with all183/10,065/
17,385 observations selected and183 usable dates per grain. Build plus complete
verification took20.995 seconds; fresh separate verification11.075 seconds.
This is replay of captured live evidence, not a new live/API run. No durable
receipt or product publication resulted; the original failed report was unchanged.
Local manifest `a0e4c49d004b95cae83bff633de5cb103f0b48f109c82cb5e2796e126185f04e:563054`.
The fresh full-interval CLI/durability gate remains open.

## Final connector closure — October 4, 2026

Fresh live run `de9648fcb92149a98d66aba51e4f667f` completed with
`stage=complete`, `outcome=candidate_verified`, no error and interval
April2–October1 inclusive. Its local report is
`data/connector-local/runs/de9648fcb92149a98d66aba51e4f667f/report.json`.
All183 national,10,065 facility and17,385 generator observations were selected;
each grain has183 usable dates. The facility advertised-total mismatch remains
visible/nonblocking; no completeness or revision-recency guarantee follows.

Exact manifest:
`f74027258fdbf78ba040128b4761166c15249177365df4eba7db1bd5f5232cd0:563052`.
The report records local success; it is not itself a durable receipt. Separate
configured-bucket GET-only reconstruction with EIA disabled and three S3 workers
verified all2054 durable graph objects and full semantic replay, closing the
initial candidate/storage gate. All six connector phases are complete within
candidate and immutable storage scope; product activation/outcomes remain deferred.
See [reviewable closure measurement](evidence/2026-10-04/initial-interval-recovery.json).
