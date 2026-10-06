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

### Controlled Docker adapter implementation

Analytical-runtime Phase 2 supplies `DockerRuntime`, `BoundedDockerControl`,
private input staging and an explicitly opened `OwnershipLedger`. Construction
starts no Docker operation. The adapter implements the existing `ReviewedRuntime`
port; implementing that port does not establish reviewed readiness or inject it
into the product API. Serving-process composition is still Phase 3.

Inputs are copied/verified as `0444` digest files into private `0700` execution
directories. The completed directory is sealed as `0555` and receives one
read-only, nonrecursive bind at `/inputs`; its identity and files are revalidated
before creation. Recovery accepts exactly private `0700` or sealed `0555`
directories, retaining UID and symlink checks. The fixed image receives no
request-selected image, environment, mounts or network. The CLI uses explicit local
`--host` arguments, no shell, and independently bounded concurrent streams.
Creation intent is persisted before Docker creation. Recovery preserves the
single admission slot, staging and application leases through unconfirmed death,
removal or cleanup; only confirmed cleanup permits reuse. The supervisor will
invoke the explicit recovery owner rather than relying on garbage collection.

The corrective implementation adds `quota-disk` for native Linux Docker with a
dedicated finite ext4 spill filesystem. `tmpfs-smoke` remains smoke-only. Unsupported
or missing filesystem prerequisites fail closed without fallback. Controlled
tests do not close real isolation/termination evidence, measured budgets,
user-owned T1.7 or the separate API-enablement gate.

## Explicit local supervision (Phase 3)

The executable is delivered; use `--help` without constructing any resources:

```sh
.venv/bin/python -m outage_explorer.entrypoints.http.analytical_startup --help
```

After complete matching runtime evidence and separate API-enablement direction,
the intended local invocation is:

```sh
.venv/bin/python -m outage_explorer.entrypoints.http.analytical_startup \
  --config /private/tmp/outage-runtime-reviewed.json
```

The bounded nonsecret JSON has exactly `profile` and `evidence` properties.
`profile` uses the `RuntimeProfile` field names; omit default fields or serialize
all fields, including the worker limits and fixed isolation policy. `evidence`
may be `null` for a candidate; candidates cannot start. A reviewed record has
`profile_identity`, `controlled_report`, `isolation_report`, `termination_report`,
`storage_report`, `measurement_report`, `reviewer` and ISO-date `reviewed_on`.
The identity must equal the complete profile digest and each report value must
be its SHA-256 digest. Digest-shaped fixture values do not establish evidence;
Phase 4 owns actual reports, their review and readiness. Duplicate/unknown keys,
unknown worker limits and files larger than 64 KiB are rejected. Never include
credentials, cookies, SQL, environment dumps or protected cells in this file.

The inert builder forwards to an explicit process-owned supervisor. Start checks
evidence before opening the single-owner lock; reconciles the prior exact
container intent before staging/cache reclamation; constructs the verified cache,
trusted S3 readers, launcher, fresh cursor key and ephemeral results; and starts
periodic recovery, preview-expiry and result cleanup before admitting work.
Transfer sessions renew their bounded budget for each serialized cold cache load.
Existing artifact defaults and the 30,000-row preparation bound remain candidate
allowances, not representative measurements.

Shutdown stops admission and cancels outstanding work. Active execution, preview
leases, result readers and unresolved recovery retain their resources and lock;
repeated close retries after those leases finish. Cleanup proves worker death and
removal before deleting its exact staging. Expired previews retain active pins;
results retain active readers. Cache teardown rejects pinned inputs. Unknown
cache paths fail closed. A restart loses query/cursor mappings and uses a new
cursor signing key; old query IDs return 404 and old preview cursors 410, without
re-execution. Catalog, health and the independent refresh worker remain separate.

Only a single serving process on loopback is supported by this local executable.
Reloader, debug, fork-inherited resources and multiple-process modes are rejected;
`--workers`/`--reload` are unsupported and `WEB_CONCURRENCY` must be absent or `1`.
This constraint does not select the final production WSGI topology.

**Readiness remains closed:** tmpfs profiles fail evidence validation. The disk
backend now validates real host prerequisites at explicit startup; there is no
reviewed real-runtime record yet. Phase 4 must supply isolation, termination,
storage and measurement evidence before separately authorized Phase 5 enablement.

## Native Linux disk spill prerequisites (corrective T4.S1–T4.S3)

The selected target is **native Linux Docker on a Linux VM or EC2**. The controller
must run on that daemon host, in its mount namespace, under UID/GID **65534:65534**.
It needs trusted host access to the root-owned `/run/docker.sock` (the conventional
`/var/run/docker.sock` symlink is accepted). Worker containers receive no socket,
host credentials, devices or privileges. Docker Desktop and remote/proxied daemons
are unsupported by this disk backend. A Linux VM on your Mac is a suitable host;
the Mac's existing Docker Desktop daemon is a different target.

Provision a **new, dedicated, fixed-capacity ext4 filesystem**, owned by 65534,
mounted `rw,noexec,nosuid,nodev`, with no nested mounts or foreign files. The current
internal image profile caps temporary storage at 16,777,216 bytes and 4,096 inodes.
Actual filesystem `f_blocks * f_frsize` and `f_files` must be positive and no larger
than those bounds. The entire filesystem is reserved to one analytical runtime;
its kernel allocation ceiling covers multiple files, open/unlinked files and
directory metadata. DuckDB's limit is an additional engine constraint.

The following is a **reviewable Linux host setup example, not executed here**.
It creates a fresh ordinary image file and mounts it via a loop device; it does
not format any existing device. Run only on the chosen Linux host after approval
of that host's provisioning. `set -e` and the existence check stop reuse of an
existing image. This is a candidate local setup, not an EC2 storage deployment.

```sh
set -e
test ! -e /var/lib/outage-analytical/spill.img
sudo install -d -m 0711 /var/lib/outage-analytical
sudo install -d -m 0700 /var/lib/outage-analytical/spill
sudo install -m 0600 /dev/null /var/lib/outage-analytical/spill.img
sudo fallocate -l 16777216 /var/lib/outage-analytical/spill.img
sudo mkfs.ext4 -F -m 0 -N 1024 -O ^has_journal /var/lib/outage-analytical/spill.img
sudo mount -o loop,rw,noexec,nosuid,nodev /var/lib/outage-analytical/spill.img /var/lib/outage-analytical/spill
sudo rmdir /var/lib/outage-analytical/spill/lost+found
sudo chown 65534:65534 /var/lib/outage-analytical/spill
sudo chmod 0700 /var/lib/outage-analytical/spill
```

Configure the normal application supervisor/test command to run as 65534 with
trusted Docker-socket access; private staging/cache/result roots must also be
owned by that user. Do not run the worker privileged or loosen spill-root ownership
to work around host setup. The API code never mounts, formats or resizes storage.
For host restart, provision the mount again before startup; a missing mount fails
closed. Any changed filesystem identity requires a new profile and evidence review.

After setup, run this read-only command as the configured controller user to
obtain the explicit filesystem identity and capacity for the candidate profile:

```sh
python3 -c 'import os; p="/var/lib/outage-analytical/spill"; s=os.stat(p); v=os.statvfs(p); print(f"{os.major(s.st_dev)}:{os.minor(s.st_dev)}:{v.f_fsid}", v.f_blocks*v.f_frsize, v.f_files)'
```

Set `temporary_backend: "quota-disk"`, `temporary_root` to that exact mount,
`temporary_filesystem_identity` to the first printed value, `temporary_inodes`
to 4096, and `docker_executable` to the actual absolute Linux CLI path (commonly
`/usr/bin/docker`). These fields and the fixed `ipc: "none"` policy participate
in the profile digest. Old profile/report identities are invalidated.

Startup checks native daemon version/platform/kernel/hostname/socket and the
ext4 mount, identity, flags, ownership and capacity. Each execution locks the
filesystem pool and durably records its exact spill path before allocating a
private directory. Only that directory is bound at `/tmp`; recursive binds are
disabled. Docker `--ipc none` retains a private IPC namespace and disables the
extra `/dev/shm` mount. Uncertain worker death or removal retains the spill, input
pins, admission slot and pool lock. Durable preparing/creating/removed phases
support restart recovery without treating an absent ambiguous create as death.
Foreign pool contents, symlinks, replacement, capacity drift and failed cleanup
fail closed; recovery never deletes unrelated host files.

Host setup and controlled tests are not proof of enforcement. T4.3 must execute
the native Linux aggregate/open-unlinked byte, inode, noexec, lifecycle/recovery
and measurement probes; T4.C reviews their exact matching reports. API enablement
remains a separate later authorization.

Primary references: [ext4 kernel structures](https://www.kernel.org/doc/html/latest/filesystems/ext4/overview.html),
[Docker daemon-host bind mounts](https://docs.docker.com/engine/storage/bind-mounts/),
and [Docker IPC modes](https://docs.docker.com/reference/cli/docker/container/run/).

### Recorded dedicated Colima validation (October 5, 2026)

An explicitly approved local VM now exists as Colima profile `outage-runtime`:
native aarch64 Ubuntu 24.04.4, kernel 6.8.0-117-generic, Docker 29.5.2, 4 CPUs,
6 GiB RAM and a 20 GiB data disk. These VM sizes are validation candidates,
not measured product budgets. The original `default` profile remains stopped
and the host Docker context remains `desktop-linux`. No Mac directory mounts,
SSH-agent forwarding, SSH-config edits or automatic context activation were used.

Reusable, reviewable helpers live in [native-linux-validation](native-linux-validation/).
They deliberately target only this dedicated VM and fresh guest directories:
Before exporting HEAD, commit the reviewed implementation, including the O_PATH
traversal correction: `git archive` omits uncommitted changes. The diff check below
refuses a stale committed source export; do not remove it to bypass pending edits.

```sh
sh infrastructure/analytical-worker/native-linux-validation/start-colima.sh
colima ssh --profile outage-runtime -- sh -s < infrastructure/analytical-worker/native-linux-validation/prepare-guest.sh
git diff --quiet HEAD -- src tests infrastructure/analytical-worker pyproject.toml README.md
git archive --format=tar --output=/private/tmp/outage-runtime-source.tar HEAD src tests infrastructure/analytical-worker pyproject.toml README.md
colima ssh --profile outage-runtime -- sudo tar -xf - -C /opt/outage-runtime-validation < /private/tmp/outage-runtime-source.tar
colima ssh --profile outage-runtime -- sh -s < infrastructure/analytical-worker/native-linux-validation/build-guest.sh
```

The archive includes committed code/tests/build files only; it excludes Git
history, `.env`, AWS configuration and host credentials. Archive the reviewed
implementation revision. The preparation helper refuses an existing spill image
or source directory; do not repeat fresh provisioning on the existing VM.
For the recorded VM these steps are already complete. The root-owned loop image
contains 1,024 inodes and 16,494,592 allocatable filesystem bytes, under the fixed
16 MiB worker ceiling. `/var/lib/outage-analytical` stays execute-only to other
users; secure directory traversal uses Linux O_PATH for ancestors and readable
descriptors only for the selected private root.

Create the candidate profile as the trusted controller after verifying the
guest Docker socket's group (991 in the recorded VM):

```sh
colima ssh --profile outage-runtime -- sudo setpriv --reuid=65534 --regid=65534 --groups=991 env -i PATH=/usr/bin:/bin HOME=/nonexistent /opt/outage-runtime-validation/.venv/bin/python - < infrastructure/analytical-worker/native-linux-validation/create-profile.py
colima ssh --profile outage-runtime -- sh -s < infrastructure/analytical-worker/native-linux-validation/run-isolation.sh
```

`create-profile.py` refuses to overwrite an existing profile. The recorded
candidate already exists at `/var/lib/outage-runtime-validation/candidate.json`;
it has null readiness evidence and cannot start the product API. An image/config
change requires a new matching candidate/report review. The run helper executes
only synthetic `runtime_docker` probes as 65534 with trusted daemon access and a
clean environment. It never executes representative measurements, starts the
product API, passes cloud credentials or retrieves/publishes data.

The latest matching-image execution passed **19 real Docker probes**, with one
measurement test deselected; the focused native Linux execute-only traversal
regression also passed. It verified zero owned containers, staging directories,
spill execution directories and temporary recovery ledgers after cleanup. The
[unreviewed directory-mount evidence bundle](../../docs/specs/analytical-runtime/evidence/2026-10-05-colima-isolation-directory-mount.json)
binds the final immutable image/profile and individual report hashes. The earlier
[pre-fix isolation bundle](../../docs/specs/analytical-runtime/evidence/2026-10-05-colima-isolation.json)
is retained as historical evidence for a different image/profile. The final run
also confirms recovery accepts the exact sealed `0555` staging mode while
preserving private ownership checks. No performance measurements were run.

The initial Colima wrapper provisioning exited with a killed subprocess and
`colima status` reported incomplete wrapper metadata. Bounded native guest
checks, actual Docker probes and trusted `colima list` verified the VM/daemon
running. Use the explicit profile SSH command above; no default context repair
or profile reset was performed. This wrapper metadata observation does not
establish product runtime readiness.

T4.3 is **partial**: representative old/current public inputs, independently
authorized existing refresh/API overlap, S3 transfer/storage coverage, measured
budget review and T4.C remain missing. Synthetic probes do not replace these
measurements, and Phase 5 API enablement remains gated.

## Delivered user-owned validation harness (Phase 4)

`tests/acceptance/test_query_runtime.py` now provides the two separate commands
below. These commands are **instructions for a later explicitly directed run**;
implementing this harness has not built an image or contacted Docker. The entire
normal suite skips these tests. Both an exact `-m runtime_docker` or
`-m runtime_measurements` selection and `OUTAGE_RUNTIME_TEST_PROFILE` are required.
Setting the profile alone, selecting a file alone, `-m 'not runtime_docker'`, or
compound marker expressions cannot start Docker. An explicit selected run fails
on invalid prerequisites; it never substitutes controlled adapters or enables API
resources. The test harness accepts `evidence: null` candidate profiles directly;
it does not change the production supervisor's matching-evidence requirements.

Prepare a dedicated, nonsecret JSON profile with the Phase 3 format. Use **new,
private validation-only roots**, never the running product's cache/staging/result
roots. On a Linux Docker host, a minimal candidate looks like:

```json
{
  "profile": {
    "image_id": "sha256:<exact 64 lowercase hex digits from image inspection>",
    "daemon_endpoint": "unix:///var/run/docker.sock",
    "docker_executable": "/usr/bin/docker",
    "platform": "linux/amd64",
    "daemon_version": "<exact local server version>",
    "filesystem_identity": "<reviewed identity of this validation filesystem>",
    "staging_root": "/tmp/outage-runtime-validation/staging",
    "cache_root": "/tmp/outage-runtime-validation/cache",
    "result_root": "/tmp/outage-runtime-validation/results",
    "temporary_backend": "quota-disk",
    "temporary_root": "/var/lib/outage-analytical/spill",
    "temporary_filesystem_identity": "<exact major:minor:fsid from provisioned mount>",
    "temporary_inodes": 4096
  },
  "evidence": null
}
```

Replace placeholders using the bounded scalar commands in the T1.7 checklist;
use `linux/arm64` when that is the actual daemon platform. Bind mounts must be
available at the same absolute paths to the native Linux daemon. Provision the
disk mount above and run as the configured UID/GID. Docker Desktop fails this
backend's host validation. The profile's immutable image ID must exist locally.
`OUTAGE_RUNTIME_DOCKER_EXECUTABLE` may select an absolute executable path; otherwise
the harness resolves Docker on PATH once; it must match `docker_executable` in
the hashed profile. The production controller then runs
that exact executable with an explicit daemon endpoint, clean environment, bounded
I/O and no shell. No image pull/build occurs inside the tests.

After explicit user direction, run isolation/lifecycle validation:

```sh
OUTAGE_RUNTIME_TEST_PROFILE=/private/tmp/outage-runtime-profile.json \
  .venv/bin/python -m pytest -q tests/acceptance/test_query_runtime.py -m runtime_docker
```

The harness validates exact image/daemon identities before preparing private
resources. It exercises the actual worker entrypoint/canonical response and uses
probe-only Python entrypoint overrides with the production launcher's same image,
UID, capabilities, root/network policy, selected temporary filesystem and exact input-file staging. Probe
scripts contain synthetic public values and fake credential canaries only. The
probes cover PID/IPC/network namespace policy, fake host repository/raw/cache/
credential denial, Docker socket denial, environment isolation, read-only inputs
and source replacement, cgroup v2 CPU/memory/PID ceilings, actual CPU throttling,
OOM kill, process-limit exhaustion, aggregate disk/inode ENOSPC, deadlines, crashes, surviving
child termination, cancellation and stalled/overflowing stdin/stdout/stderr.
Lifecycle probes induce lost-create responses and failed removal against real
containers without stopping the daemon. They prove busy admission and retained
input files/leases until death/removal reconciliation, and restart recovery of a
persisted container intent. A missing synthetic daemon endpoint is also checked.
Control failures are induced locally; the harness does not reboot the host or
restart a real Docker daemon. Logical cleanup/recovery does not wait 900 seconds
or establish wall-clock expiry evidence by itself.

`test_disk_spill_readiness_requires_supported_backend` now proves aggregate
open/unlinked-file exhaustion, inode exhaustion, noexec and spill reclamation on
the selected disk backend. `tmpfs-smoke` still fails this gate. No real Linux
quota probe was executed in the corrective implementation; a passing subset of
the harness cannot establish readiness.

### Representative public inputs and existing overlap workload

Measurements currently require a **Linux host with procfs and cgroup v2 Docker**.
Other hosts produce an explicit unsupported measurement gate. Prepare two
independently approved, already verified immutable public-projection snapshots:
`old` (retained while `current` runs) and `current`. Each must contain usable
national/facility/generator data over the initial inclusive April 2–October 1,
2026 interval or a reviewed larger retained interval. Use the public projection
schemas from `PUBLIC_DATASETS`, not modeled provenance/raw artifacts. Include
all verified files, exact SHA-256, bytes and rows. Record actual grain/date/entity
coverage and why these are representative with the separately reviewed evidence;
the harness never labels its small synthetic canaries representative.

Create a separate nonsecret measurement manifest (maximum 1 MiB; reports remain 64 KiB), with exactly these fields:

```json
{
  "old": {
    "national": [{"path":"/absolute/old/national.parquet","sha256":"<64 lowercase hex>","byte_count":123,"rows":183}],
    "facilities": [{"path":"/absolute/old/facilities.parquet","sha256":"<64 lowercase hex>","byte_count":456,"rows":10000}],
    "generators": [{"path":"/absolute/old/generators.parquet","sha256":"<64 lowercase hex>","byte_count":789,"rows":20000}]
  },
  "current": {
    "national": [{"path":"/absolute/current/national.parquet","sha256":"<64 lowercase hex>","byte_count":123,"rows":183}],
    "facilities": [{"path":"/absolute/current/facilities.parquet","sha256":"<64 lowercase hex>","byte_count":456,"rows":10000}],
    "generators": [{"path":"/absolute/current/generators.parquet","sha256":"<64 lowercase hex>","byte_count":789,"rows":20000}]
  },
  "refresh_pid": 12345,
  "api_pid": 12346,
  "api_port": 8000
}
```

Numbers/hashes above are format examples, **not measurements or verified inputs**.
The manifest rejects unknown/duplicate keys, symlinks, nonpublic columns,
empty grains, invalid PID/port values, wrong hashes/bytes/rows and input budgets.
The worker rechecks full public types before executing. `refresh_pid` must identify
an independently authorized, already running refresh workload; `api_pid` identifies
its separately running local API. The sampler reads numeric resource metrics and
Linux process-start ticks to reject PID reuse; it neither starts nor restarts either
process. Keep those processes running throughout the measurement interval and
record their approved workload identity/timestamps separately. API sampling sends
only bounded, unauthenticated `GET /health` to `127.0.0.1:api_port`; it sends no
cookies, credentials, SQL, refresh requests or publication operations. It establishes
health responsiveness during overlap, not authenticated product API acceptance.

After separate explicit user direction for measurements:

```sh
OUTAGE_RUNTIME_TEST_PROFILE=/private/tmp/outage-runtime-profile.json \
OUTAGE_RUNTIME_MEASUREMENT_INPUTS=/private/tmp/outage-runtime-inputs.json \
  .venv/bin/python -m pytest -q tests/acceptance/test_query_runtime.py -m runtime_measurements
```

The workload scans all three grains with count/outage aggregation, then runs an
ordered full generator projection through the real bounded worker/encoder. It
retains each completed immutable canonical result in the real spool/index and
pages the result without another SQL execution. It retains the old snapshot's
input bytes/results throughout current cold/warm runs. Each run reports preparation,
aggregate/output execution and page latency, output bytes and retained rows. The
cold/warm terminology means a **validation-owned verified local-copy cache**;
it does not measure the product S3 cache, S3 downloads, or drop host page caches.
Shared old/current content is a documented cache hit, not a cold transfer. Reports
record cumulative local-copy bytes so warm transfers can be compared exactly.

Overlap sampling records observed cache/staging/spool/index high-water bytes,
container memory/CPU, host available memory, refresh/API RSS and CPU counters,
harness CPU/RSS, health response latency/failures and sampling coverage/failures.
These are sampled maxima, not guaranteed peaks; representative queries must last
long enough to obtain container samples. Linux host memory and process samplers
fail closed when unavailable. Background `docker stats` output is capped and uses
only numeric formatting, never full inspection. Very short workloads, process
exit/PID reuse, inaccessible measurements or unavailable health fail the run.

Dedicated native Linux ext4 spill enforcement passed the matching isolation probes;
representative query spill high-water coverage remains unmeasured. External
refresh/S3 transfer evidence is explicitly `not_run`; obtain it from the independently authorized existing refresh
record and correlate its interval, identity and measured resources during review.
The harness never starts a refresh or publication merely to fill these gaps. API
health-only sampling cannot close Phase 5 live authorization/paging acceptance.
Review preparation/overall/control/termination bounds, API latency and host pressure
alongside all measured allowances before recording approved budgets. Defaults remain
candidates; reports never mutate them or grant readiness.

### Reports and recovery after a failed validation run

October 5 measurement continuation found two existing local initial-interval
candidate graphs and derived their exact public projections using the same domain
decoder/schema/column mapping as the product cache. The preparation helper is
[`prepare-public-inputs.py`](native-linux-validation/prepare-public-inputs.py);
it preserves all 549 daily partitions per snapshot, verifies modeled identities,
and exports only public columns. It does not replay the full raw/disposition
graph or establish publication. Its private `snapshots.json` deliberately omits
overlap PIDs until a real independently authorized Linux workload is available.
Both candidates have identical public content; the current snapshot is a cache
hit, not a second cold transfer. Descriptor size is 274,689 bytes, which exposed
the former 64-KiB manifest cap; a bounded 1-MiB cap now admits the layout without
changing independent file/cache limits or the 64-KiB evidence limit.

The partial guest runner
[`run-analytical-only.py`](native-linux-validation/run-analytical-only.py) accepts
only `old`/`current` keys and samples numeric host/storage/container metrics with
no API requests or refresh process. Invoke in the existing guest checkout with
the same clean environment/controller identity as `run-isolation.sh`, add
`PYTHONPATH=/opt/outage-runtime-validation`, and pass `--inputs` to the guest's
private snapshot manifest. It always leaves full representative overlap/S3 gates
`not_run`; it cannot produce readiness. Preparation and failed-query metrics are
retained. The actual run failed before container creation: **141,646 mount argv
bytes exceed the unchanged 131,072-byte controller allowance**, although the
worker request is only 58,458 bytes. No product budget was enlarged to force a
pass. See the [failed measurement report](../../docs/specs/analytical-runtime/evidence/2026-10-05-colima-measurements-failed.json)
and [review gaps](../../docs/specs/data-api/runtime-evidence.md).

Every configured test writes a new private (0600), bounded (64-KiB maximum) JSON
report under the profile staging root's parent, `validation-reports/`. Reports contain
image/profile/platform identities, fixed gate names/statuses and numeric metrics
only. They never copy stdout/stderr, exception text, script bodies, public cells,
host paths, environment dumps or auth data. The representative manifest is referenced
by SHA-256. Files are exclusive, cannot overwrite evidence, and remain `unreviewed`.
Record exact invocation/host/image/profile, failures and report digests in
`docs/specs/data-api/runtime-evidence.md` only after the actual user-owned run.

Failed cleanup retains its exact private ledger/staging instead of claiming death
or releasing ownership. Preserve those files and container identity for explicit
reconciliation; do not blindly delete directories or use global Docker prune.
Normal successful tests remove only their own container, staging, ledger, copy
cache and result spools. Validation roots themselves and sanitized reports remain.
No test enables the analytical API, changes production readiness, deploys, accesses
operational PostgreSQL/S3 credentials, performs source retrieval, or publishes.

For correlation, separately export only the following numeric fields from the
**existing authorized** refresh/S3 measurement record: `interval_start_epoch_seconds`,
`interval_end_epoch_seconds`, `refresh_process_start_ticks`, `bytes_transferred`,
`cache_peak_bytes`, `refresh_disk_peak_bytes`, `spill_peak_bytes`, and
`refresh_cpu_seconds`. Include immutable generation/report SHA-256 identities,
collector identity/version and whether peaks are sampled or enforced. Preserve
its digest and interval alongside the harness report. The harness does not create
or ingest this external record and does not report those values as observed;
missing producer instrumentation or unmatched intervals remain explicit missing
evidence. Use existing measured records only; estimates, candidate allowances and
local-copy byte counts cannot substitute for S3 transfer or disk-spill evidence.

## Bounded API SQL inspection (ADR-0054)

API composition no longer supplies the in-process SQL parser. Missing explicit
inspection configuration fails with a safe unavailable result before inputs.
Controlled tests explicitly inject their parser; the analytical container retains
its separate SQL reinspection.

`SubprocessSqlInspector` takes `InspectionBounds` and absolute trusted Python and
Linux `prlimit` paths. No numeric runtime defaults are supplied. Linux hard
address-space/CPU/core/file limits apply before isolated Python starts; SQL and
fixed AST limits travel through bounded stdin. The child has a minimal environment,
closed inherited descriptors and no application state or approved data inputs.
This is parser resource containment, not a filesystem/network sandbox or a SQL
execution capability.

Pass the adapter explicitly as `inspector=` to `build_analytical_resources`;
construction launches no child and its resources close cancels/reaps inspection.
The current CLI does not invent parser settings from analytical-worker budgets.
Reviewed configuration delivery remains pending before SQL activation. One slot
rejects excess work; wall-clock/output bounds and validated scope protect the
parent. Unknown or uncertain termination retains capacity until explicit cleanup
confirms process/group death. There is no in-process fallback.

Candidate native checks (no API/Docker/cloud or performance measurement):

```sh
.venv/bin/python -m pytest -q tests/integration/test_sql_parser_process.py
```

They require Linux and `prlimit`; other platforms skip. Test-only values (four
seconds wall, one CPU second, 256 MiB address space) are not reviewed budgets.
Review launcher/interpreter identity and concrete bounds before readiness.

### Parser ownership and review configuration

Use `--inspection-config PATH` alongside the analytical runtime config. The
separate file has exactly `profile` and `evidence`: profile includes all eight
`InspectionBounds` fields, `python`, `prlimit`, `setpriv`, `ownership_root` and
the three corresponding `*_sha256` executable identities. Evidence is null for
a candidate; a reviewed record has `profile_identity`, `controlled_report`,
`native_report`, `reviewer`, and ISO `reviewed_on`. Missing/mismatched review
fails before API construction. Records still require substantive human review;
well-formed digests do not prove readiness. Parser budgets have no defaults.

Explicit parser start creates the final private ownership directory (its parent
must already exist) and locks the stable `parser.lock`. Never delete/replace that
lock or ownership root during recovery. The fixed child inherits only its lease
descriptor; owner loss retains admission until the child exits. Setpriv applies
parent-death SIGKILL and no-new-privileges before limits/interpreter startup; the
child verifies expected parent identity before SQL reading. Replacements acquire
the lease only after all inherited descriptors close. Foreign PIDs/files are
never killed or removed. Bootstrap owns explicit start/rollback/close.

These changes preserve the existing analytical image/profile identity. Native
parser tests now include owner SIGKILL/replacement, inherited lease retention and
wrong-parent rejection. Candidate verification does not approve limits or enable
endpoints. Without the flag, SQL inspection remains unavailable.
