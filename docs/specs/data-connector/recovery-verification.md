# Connector artifact recovery verification

Phase 5 verifies contributor storage graphs with controlled SDK behavior.
It does not establish live AWS availability or product publication guarantees.

`tests/integration/test_s3_artifacts.py` uses a real Boto3 client with Botocore
Stubber for request-model validation, and an injected SDK-shaped transport with
real `StreamingBody` objects for deterministic faults. No test uses configured
AWS credentials or bucket access. Covered cases include conditional creates,
identical/conflicting bytes, transient/uncertain/partial writes, missing,
truncated and corrupt readback, attempt/deadline/file/graph/wire caps, closed
streams and sanitized failures. Successful PUT responses and ETags alone cannot
produce verified acceptance. No adapter overwrite, deletion or listing exists.

`tests/integration/test_connector_artifacts.py` exercises explicit CLI operations,
real Parquet, and the controlled S3 adapter. Recovery starts with empty staging,
with EIA and real credential construction forbidden. A later all-excluded
candidate retains original modeled rows and origins. Its complete graph includes
ancestor manifests, current and inherited raw/page evidence, base/unchanged
modeled dependencies, dispositions and ledgers. Recovered manifests, summaries,
exact modeled values and origins compare with the original. Full verification
also replays sanitized source strings/order and exact derived values.

Dependency upload/readback, final-manifest upload/readback and fresh full-replay
failures cannot return a durable receipt. Prior objects remain recoverable.
Identical retries verify existing bytes and can complete a previously interrupted
transfer; conflicting bytes fail without replacement. Missing dependencies,
conflicting references, descriptor tampering and graph caps fail recovery.
A failed recovery can leave unconfirmed local staging; retry into a new empty
location. Save the exact manifest reference with its configured bucket/prefix.
The CLI prints it only after complete verification; it is not an active pointer.

Run the two suites or the full documented checkpoint:

```sh
.venv/bin/python -m pytest tests/integration/test_s3_artifacts.py tests/integration/test_connector_artifacts.py
make check
```

This supports AC5 durable replay and AC17–AC18 **artifact** integrity/recovery
portions only. Full AC16–AC18 remain open: configured-bucket checks, active
publication, reader pinning, authorization, recovery of PostgreSQL refresh
outcomes and uncertain commits have separate evidence requirements. No live
EIA request, AWS write, provisioning, retention policy or deletion was performed
by the controlled checkpoint. Phase 6's separately authorized checks are in
[aws-setup.md](aws-setup.md).


## Default candidate-to-S3 execution (ADR-0042)

Candidate CLI runs now collect/verify locally and persist the full graph to S3 by
default. `--local-only` opts out. Controlled tests cover configured staging from
flags/JSON, complete source-disabled recovery after a default run, missing S3
configuration before retrieval, and S3 failure preserving the local manifest/report
for explicit retry. Successful output is `candidate_s3_verified`; failed persistence
prints a safe code and `local_manifest` for `--operation persist`. Local report
success cannot establish durable success. No live/cloud evidence follows from
these controlled one-command tests.

Default-workflow verification on October 4, 2026: final `make check` passed
825 tests, dependency validation, Ruff lint/format, strict mypy and wheel/sdist
builds. This includes the new controlled candidate-to-S3 tests; no live EIA/AWS
operations were performed for this change.

## Phase 6 authorized AWS and concurrency evidence — October 4, 2026

Configured target: `s3://arkham-outage-explorer/data/objects/`; region `us-east-1`.
The user separately authorized these writes. No deletion, bucket listing,
infrastructure change, active publication or PostgreSQL outcome was performed.
Exact object keys are SHA-256; each graph dependency was conditionally created
and hash/byte checked before the final root, followed by fresh graph replay.

One-day exact root:
`daea78aca27c24b09ef1809a3ecf3621f4845ce007f7454885be91d8f62c406d:21341`;
75 objects/687,569 graph bytes. Sequential persistence/readback passed 21.958 s;
parallel identical-object retry/readback passed 8.154 s. These are different
upload states. Fresh empty-staging recovery with EIA_API_KEY removed passed
6.256 s sequential and 2.825 s parallel, returning the same exact receipt.

Exact-prior rerun root:
`4163a962a3bc069cb72ac247a86165b394b05053c0c00d015e7877f564ef7fc4:39913`;
150 objects/1,438,271 bytes, including the first root and all required ancestry.
Parallel persistence/readback passed 19.276 s. Full replay checked schemas,
exact modeled values, quality, ledgers and source origins before issuing a receipt.
See [measurements](evidence/2026-10-04/measurements.json) and
[resource evidence](resource-evidence.md) for versions, configuration and limitations.

Controlled concurrency suites verify actual endpoint/PUT/GET overlap, reversed
completion order, exact recorded-input values/quality and inherited recovery,
conditional identical/different collisions, aggregate wire/object races, failed
dependency/final-root/readback, interruptions, closed bodies and joined workers.
Default candidate-to-S3 configuration uses the independent transfer setting.
Retained-invalid/absent/all-excluded cases are controlled injections, not claimed
live observations. Initial-interval full verification and backend recovery remain open.

Inherited parallel empty-staging reconstruction passed 5.760 seconds with
`EIA_API_KEY` removed: the exact same 150-object/1,438,271-byte receipt returned,
with full inherited manifest/evidence replay. Peak process RSS was 143,147,008
bytes. Its fresh staging contains precisely the graph bytes, with no source work.


Page-fetch extension controlled recovery includes supplemental sanitized transport
JSON objects (used and unused lookahead) as exact immutable graph dependencies.
Controlled parallel PUT/readback and empty-staging recovery preserve them without
source access; replay rejects missing/corrupt or canonically inconsistent audits.
Legacy manifests remain byte-compatible when their optional transport field is
absent. These extension checks are controlled SDK evidence; no new full initial
live candidate or new configured-bucket graph was produced for this extension.

ADR-0050 recovery verification now rebuilds bounded day partitions from fully
validated evidence in local immutable staging. These derived objects are excluded
from exact manifest/S3 dependencies and consume the same local write-session
object/byte budget. No cached verification flag skips raw semantic checks.
Existing complete graph plus derived staging must fit; overrun aborts rather than
producing a receipt. October4 source-disabled full-interval local reproduction
succeeded; it used captured local live evidence, not configured-bucket recovery.

## Full initial durable-graph closure — October 4, 2026

CLI `recover --s3-workers3` against the existing configured bucket/profile and
exact manifest `f74027258fdbf78ba040128b4761166c15249177365df4eba7db1bd5f5232cd0:563052`
returned verified recovery with2054 objects/63,420,955 graph bytes. It performed
GETs only: no EIA key/source work, PUT, prefix listing, deletion or infrastructure
change. Full hash/schema/value/origin/quality/disposition/ledger replay succeeded,
and loaded recovered summaries exactly equal the fresh live run report.

Measured recovery93.154seconds, peak processRSS154,238,976bytes. Fresh ephemeral
staging was `/var/folders/mj/1jkw87w51xs_5tt45xj8jvtr0000gp/T/outage-phase6-close-omjac2pb/recovered`;
it held2857 graph-plus-derived local objects/80,516,102bytes. The803 derived objects
are local verification staging under ADR-0050, excluded from the durable graph
and receipt. The source report remains unchanged at
`data/connector-local/runs/de9648fcb92149a98d66aba51e4f667f/report.json`.

[Tracked measurement](evidence/2026-10-04/initial-interval-recovery.json) preserves
nonsecret receipt/resources and exact summaries even if ephemeral staging is
removed later. This closes all six connector phases, not product publication,
authorization, durable operational outcomes or deployed restart recovery.
