# Connector retrieval troubleshooting

## October 4, 2026: metadata echo and facility ordering

User run `6b28e85f3d1c48c19f64c334c246f072` failed with `error=retrieval`
before any route completed. Bounded live reproduction established two adapter
assumptions that prevented the one-day run:

- The metadata endpoint returned HTTP 200 and `request.params: []`. EIA represents
  the parameterless metadata request this way. The adapter required a dictionary.
  It now accepts an empty array only for that metadata request, after validating
  its route; data-page echoes still require objects. Evidence retains the array.
- Once metadata passed, the facility page returned `46` then `204`. The adapter's
  lexical comparison incorrectly called this an ordering regression. Numeric
  facility magnitude now governs ordering comparisons, without converting or
  changing stored identifiers. Zero-prefixed IDs remain distinct identities;
  generator IDs retain text order. The recorded ordering identity is v2. No rows
  are resorted and last-valid-record selection remains based on recorded positions.

The comparator's nondigit-facility fallback is lexical after digit-only IDs.
Mixed/nondigit live collation and broader generator-ID collation remain unverified;
this observation does not prove general EIA ordering or revision recency.

Another run (`62f3702188974e2a961a5ef71e678549`) passed the corrected checks but
exhausted request attempts under the initial defaults (2 rows/page, 3-second
timeout, one attempt). That is an enforced resource failure. It is not an invalid
row, and the probe did not establish whether exhaustion came from a transient
transport failure or retryable HTTP status.

## Verified one-day local run

With `EIA_API_KEY` exported, use the optional bounded test profile:

```sh
make connector LOCAL_ONLY=1 CONFIG=connector-smoke.json
```

Under ADR-0042, omit `LOCAL_ONLY=1` only when configured S3 persistence is also
intended; ordinary connector runs now upload and verify the graph by default.

The profile specifies September 1, 2026, local staging, 100 rows/page,
10-second request timeout, 3 attempts and a 120-second per-route deadline.
It leaves typed defaults unchanged. All other limits remain enforced.

An equivalent explicit bootstrap/CLI invocation with diagnostic-only source
instrumentation produced this verified local candidate on October 4:

- Run: `3fc2189d0dff4ecf9a19f58529de402b`.
- Manifest: `77c683fcf87c8591b037782f75d3fabaf2be7b79cc1f4c10af88d0597681bdc5:6469`.
- Report: `data/connector-local/runs/3fc2189d0dff4ecf9a19f58529de402b/report.json`.
- Received and selected: national **1**, facility **55**, generator **95**.
- All routes reached a recorded empty page. No rows were excluded.
- Facility advertised **95** and returned **55**; the report preserves this
  nonblocking diagnostic. No upstream completeness claim follows.
- Outcome: `candidate_verified`, `published: false`.

These artifacts are local, Git-ignored evidence; the reference is not an S3
durability claim. Existing failed runs were preserved. No active generation,
PostgreSQL lifecycle, cloud write, initial-interval acceptance or phase-6 completion
is implied. Peak resources and supported larger intervals were not measured.

## Regression verification

`make check` passed **764 tests without skips**, Ruff lint/format, strict mypy,
dependency validation, and wheel/sdist builds. The focused source/CLI run passed
**172 tests**. Regressions cover metadata arrays across all grains, strict data
echoes and route validation, cross-page numeric facility ordering, preserved
leading-zero identities/Parquet replay, and rejection of real ordering regressions.


## S3 fails after a verified local candidate

For a profile configured by `aws login`, Boto3 requires AWS CRT support.
`make setup` now installs pinned `boto3[crt]` and `awscrt`; an incomplete install
reports `aws_dependency` rather than a generic `internal` result. This requirement
is documented in [Boto3 credentials](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html#login-with-console-credentials).

A verified local candidate remains usable after S3 failure. Copy its
`local_manifest=SHA256:BYTE_COUNT` into the explicit persistence command:

```sh
.venv/bin/python -m outage_explorer.entrypoints.cli.connector_startup \
  --operation persist --staging data/connector-local \
  --manifest 'SHA256:BYTE_COUNT'
```

This retries storage/readback without another EIA retrieval. Session expiry,
provider availability and bucket permissions remain separate checks; installing
CRT does not renew credentials or prove cloud access.

`comparison_started` covers grain modeling and full semantic verification, not
just a quick summary comparison. An interrupted run with no manifest is not a
confirmed candidate. ADR-0050 removes per-day whole-evidence scans; current logs
include `grain_build_started/complete`, `grain_verify_started/complete` and
periodic partition counts. Verification may create bounded immutable derived
local partitions; they remain retry staging, not authoritative graph dependencies.
