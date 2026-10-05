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
