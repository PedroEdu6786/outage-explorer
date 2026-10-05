# Candidate analytical worker image

This implements one-request stdin/stdout transport around the existing preview
and query adapters. It does not enable the product API or supply a reviewed
container launcher. T1.7 isolation/limits/termination validation remains pending.

Build from the repository root (the Dockerfile-specific ignore file excludes
configuration, credentials, local data and Git history):

```sh
docker build -f infrastructure/analytical-worker/Dockerfile \
  -t outage-analytical-worker:dev .
```

Run a reference-free synthetic query without mounting any inputs:

```sh
printf '%s\n' '{"version":1,"operation":"query","sql":"SELECT 42 AS answer","relations":[]}' |
docker run --rm -i --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 512m --memory-swap 512m \
  --cpus 1 --pids-limit 32 --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  outage-analytical-worker:dev
```

The response has `version`, `operation`, and a `result` containing the existing
canonical encoding. The integer cell is the string `"42"`. The process exits
after its response; errors return only a safe code and exit status 1. There is
no HTTP server or PostgreSQL/S3 connection in this execution path.

The image installs the application package to reuse its bootstrap composition;
it currently includes the declared backend dependencies as well as DuckDB.
It never loads `.env`. Do not pass host credentials or mount the Docker socket,
repository, raw artifacts or unrestricted cache into execution containers.

## Internal protocol v1

Requests are strict JSON, at most 131,072 bytes, with no duplicate/unknown fields
or nonfinite JSON constants. They are trusted launcher messages, not a public
authorization API. The parent must authorize before preparing any inputs.

Query fields: `version: 1`, `operation: "query"`, `sql`, `relations`. Each relation
has `dataset` (a public ID) and `files`; the exact referenced grains must match
the provided relations. The worker reuses SQL inspection before engine execution.

Preview fields: `version: 1`, `operation: "preview"`, `dataset`, `files`,
`start_date`, `end_date`, `after`, `page_size`. Dates and `after` may be null.
Page size is 1–500. Output includes canonical column descriptors/cells, keyset
keys and `has_more`; the API still owns preview cursors and snapshot metadata.

Each file descriptor has exactly `sha256`, `byte_count`, `rows`. Only lowercase
64-character SHA-256 identities are accepted; paths are constructed beneath
the fixed `/inputs` root as `<sha256>.parquet`. Arbitrary paths are not accepted.
Existing adapters recheck actual hashes, sizes and public schemas before reading.

Responses are capped at 1 MiB plus 128 KiB transport overhead; query retained
documents keep their existing 1,000-row/1-MiB caps. Candidate worker engine
memory is 128 MiB and temporary storage is 16 MiB; the example container has
512 MiB total memory. These are explicit smoke-test settings, not measured
production allowances. The future launcher must enforce wall-clock deadlines
and complete container termination/reaping; the transport does not do so.

Next: implement `ReviewedRuntime` with bounded Docker lifecycle/I/O, typed
response decoding, input mount preparation and teardown; perform T1.7 validation;
then wire `DataHttpResources` through the API supervisor.

## Phase 1 profile and parent transport

`RuntimeProfile` and `RuntimeEvidence` are inert typed contracts in
`infrastructure/worker_runtime/configuration.py`; constructing them starts no
Docker process and prepares no directories. A profile requires an immutable
`sha256:` image ID, explicit local `unix:///...` daemon, platform/daemon/filesystem
identities and separate private staging/cache/result roots. It accepts only UID/GID
65534, one serving process, no network, read-only root, dropped capabilities,
no-new-privileges and no extra mounts/environment. All integer budgets are finite,
positive and independently identified; public lifetimes stay 900 seconds.

The internal v1 worker uses exact image-profile matching. Startup settings are
validated by `build_query_worker()` and translated into execution/encoding bounds;
any deviation from the image's candidate limits is rejected. The adapter's
`WorkerImageLimits` is separate from startup settings to preserve the repository's
import matrix. Tests require the two contracts to agree. There are no host
resource environment overrides, credential-bearing profiles or v1 request changes.

Candidate limits are engine memory 128 MiB, temporary space 16 MiB, preparation
30 seconds, overall 40 seconds and execution 10 seconds; encoding uses 1-MiB cells,
depth 16, 10,000 nested items, 100 columns and 64-KiB schema bytes. Candidate
container limits are 512-MiB memory/equal swap ceiling, one CPU and 32 processes.
Input/staging/cache allowances are each 2,147,483,647 bytes; result storage is
10 MiB with ten global/three per-user entries. Control and termination each have
five-second candidate bounds, cleanup interval 30 seconds, stdout 1,179,648 bytes,
stderr 65,536 bytes and JSON expansion 100,000 nodes. These limits are **unmeasured
candidates**, including contributor defaults; none establishes runtime readiness.

`WorkerTransport` serializes authorized descriptors without host paths and rejects
malformed/noncanonical responses, duplicate keys, incompatible versions/operations,
invalid descriptors/cells, count/limit disagreement, excessive expansion and
exit/error disagreement. Preview reconstructs dates and Decimals and checks exact
projection, key equality/order and original filters. Query documents preserve
canonical bytes, descriptor order and duplicate column labels, including nested
values; transport does not normalize alternate JSON representations.

Evidence references are bounded SHA-256 report identities plus reviewer/date and
a digest of the entire profile. Changing any profile field invalidates the match.
Unstarted resources, missing evidence and `tmpfs-smoke` remain unavailable.
`quota-disk` names a future supported hard-quota backend; selecting that string
alone does not implement or prove a quota. Phase 3 must verify readiness in startup,
and Phase 4 must supply/review actual denial, termination, storage and representative
measurement evidence. Phase 1 has not supplied a Docker launcher or enabled HTTP.
