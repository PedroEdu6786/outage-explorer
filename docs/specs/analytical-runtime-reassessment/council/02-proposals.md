# Small-team analytical runtime — Proposals

The authors worked independently from the same spec. Both selected Docker as a
conditional baseline; this agreement is not proof of capacity or an accepted
production decision. Their significant difference is how explicitly the host-wide
ceiling and daemon-wide recovery constrain otherwise independent execution slots.

## Proposal A — fixed small worker pool (author: rafachafa, Pragmatist)
- **Approach:** Retain isolated short-lived DuckDB containers. The actual failure is mount-metadata amplification for a 2.2-MB dataset, so change input delivery before changing engines. Copy/verify only approved public files into a private execution directory, seal it, bind it once read-only, and retain digest names and strict manifest bounds. Reject symlinks, mutable-cache hardlinks, unexpected entries and post-validation mutation; preserve host-parent protection and pin lifetime. Docker mount count becomes constant, but descriptors/validation/copying still scale with file count/bytes.
- **Concurrency:** One API owner with a fixed pool, evaluating two then four slots. Reserve aggregate worker memory/CPU/PIDs, preparation/staging, cache/pins, result/encoding/controller capacity and API/refresh headroom before input access. Each slot owns its container, staging, recovery ledger and independent writable allocation. Keep explicit busy behavior and retain all reservations while death/removal is uncertain.
- **Spill:** One externally provisioned finite ext4 filesystem per slot reuses current kernel block/inode enforcement. Multiple directories in the current shared finite filesystem are insufficient. Workers gain no mounting privileges. Project quotas are a later alternative if the operational cost of fixed filesystems is unacceptable.
- **Phase outline:** Agree target/decision revisions; define directory isolation/slots/admission/reconciliation; test mutation/cross-request denial and failure ownership; measure real one/two/four-worker cold/warm/mixed/overload/overlap; compare operating cost and managed-contract differences before acceptance.
- **Data-model changes:** Private slot-scoped lifecycle ownership; no operational schema or durable query-ID change.
- **Explicitly cut:** Broker, autoscaling, reusable warm SQL processes, API replicas and publication-layout changes. A separate bounded argv allowance is an optional diagnostic baseline, not a second mandatory permanent design.
- **Author-admitted risks:** Several spill filesystems add provision/restart work; staging is repeated; manifests still grow; Docker daemon privilege remains material. Budgets/scalability remain unverified.
- **Traces to:** FR1–FR6, TR1–TR6.

## Proposal B — execution lanes with aggregate containment (author: gamachiel, Architect)
- **Approach:** Keep isolated DuckDB as the leading candidate, replace per-file mounts with one exact finalized request directory, and make concurrency a resource model. Protect parent/directory identity against replacement, finalize read-only contents, preserve authorization and pin ownership. Do not expose a shared cache or optimize through mutable hardlinks.
- **Concurrency:** A finite set of independent lanes under one supervisor reserves worker and preparation resources before reads/downloads. Each lane needs a proven independent byte/inode spill ceiling; dedicated finite ext4 filesystems are a candidate reuse of existing mechanics. Enforce a total analytical resource ceiling in addition to per-worker ceilings, with measured API/refresh headroom; account for simultaneous downloads and disk contention.
- **Recovery:** Lane/request/container/directory identities are persisted privately. Uncertain cleanup quarantines its lane and reservations. Other lanes continue only with independent storage/capacity and a healthy shared daemon/control boundary. A daemon-wide failure closes all admission.
- **Phase outline:** Define demand/SLO/cost and compatibility criteria; accept needed decisions and evaluate one-directory input mount; implement lane accounting/recovery only after that experiment passes; measure concurrency/overload/failure/S3/API-refresh overlap before readiness.
- **Data-model changes:** Private per-lane ownership records; ephemeral query mappings remain separate and bounded.
- **Explicitly cut:** Queues, reusable workers, Kubernetes, brokers, extra API replicas, compaction and durable query metadata.
- **Author-admitted risks:** Per-lane filesystem administration, powerful daemon authority, repeated copying and unknown latency/capacity. Managed execution should win a later decision if these exceed the agreed operator budget or SLOs.
- **Traces to:** FR1–FR6, TR1–TR6.

## Additional candidate — Parquet-authoritative snapshot with a derived DuckDB serving file

This candidate was raised during the owner's follow-up about query wait time. It
is an architecture option for comparison, not a decision or a measured fix.

- **Data and build path:** Keep the verified raw/modeled Parquet graph in S3 as
  the authoritative challenge output. After a candidate graph has passed the
  existing refresh verification, build one or more persistent DuckDB database
  files from those exact Parquet objects. Verify schema, row/value parity,
  grain coverage and generation identity before the database can be served.
  Treat the DuckDB file as a rebuildable derived artifact; recovery rebuilds it
  from Parquet without rerunning EIA ingestion. Its serving location remains an
  open choice: a disposable local cache limits durable duplication but must be
  rebuilt after host loss; a durable S3 copy increases storage/transfer and
  requires its own verified upload/readback lifecycle.
- **Query path:** Continue using the pinned DuckDB engine and isolated worker,
  but open the immutable generation-specific database read-only. This could
  replace hundreds of per-file binds with a bounded small number of database
  file binds and avoid repeated Parquet decoding. DuckDB documents CTAS from
  `read_parquet` and read-only persistent files; neither published capability
  proves this app's latency, concurrent-reader behavior on its pinned version,
  or isolation configuration.
- **Publication and retention:** Build the database before changing the active
  generation reference. A failed build leaves the old Parquet/database pair
  active. Existing workers/results pin the old generation; garbage collection
  waits until all owners and continuations expire. Record and reconcile any
  uncertain upload/build/publication outcome so Parquet and DuckDB from two
  generations can never be combined.
- **Authorization:** A single database containing national, facility and
  generator tables cannot automatically preserve the current Viewer's
  national-only access just because SQL references are inspected. Either
  provide an independently enforced per-role physical input boundary (for
  example, separately verified role-scoped derived files) or prove an equally
  strong isolation control before opening a database. Keep application
  authorization before any data access and retain the isolated worker with no
  PostgreSQL/cloud credentials or network.
- **Costs and unknowns:** Adds refresh CPU/time, staging and candidate-build
  disk, a second representation, verification code, retained old-generation
  disk, and crash recovery. A warm query may be faster, but building/opening
  the database may move work into refresh or cold preparation. The available
  six-month sample is only about 2.2 MB, so there is no evidence yet that its
  query time is materially improved or that database size/build costs remain
  acceptable as retention grows. Compare complete time-to-first-page and full
  completion, cold/warm, resource high-water, database/Parquet size, build time,
  and 2/4 mixed-request behavior against the current Parquet path.
- **Contract fit:** This can preserve the Parquet challenge deliverable and
  broad DuckDB SQL if the published Parquet remains authoritative and the
  worker still executes the same DuckDB version/features. It changes the
  accepted query-input/storage layout in ADR-0007/0008 and needs a generation
  integrity/publication decision before implementation. It does not remove
  worker isolation, resource limits, admission, retained-result pagination,
  spill bounds or API/refresh headroom requirements.

### Distinguish the database choices

| Interpretation | Challenge fit | Change from accepted architecture | Preliminary assessment |
|---|---|---|---|
| Derived per-generation DuckDB file; Parquet stays authoritative | Preserves required raw/modeled Parquet output and the DuckDB SQL engine | Adds a serving artifact, build/verification lifecycle, generation binding, retention and role-scoped input proof; revises the current Parquet-query path | Worth a bounded design and comparative benchmark after measurement criteria and suitable inputs exist; not yet shown to improve the user's wait |
| Analytical PostgreSQL copy (particularly the existing operational RDS) | Parquet may still exist, but broad DuckDB SQL behavior is no longer assured | Existing RDS is reserved for operational state, and analytical workers are explicitly denied PostgreSQL access; changes dialect, trust/network boundary, capacity isolation, schema/role controls and publication/recovery | Not a small implementation update; using the current operational RDS conflicts with accepted boundaries. A separate analytical service is a larger alternative comparison |
| Replace Parquet with a database as the durable/model output | Fails the stated Parquet-or-Delta challenge requirement and reverses ADR-0001/0002 | Replaces the durable format and query/storage decision | Does not comply without an explicit challenge/scope change |

## Contract and operating comparison

This comparison was checked against primary documentation on 2026-10-05. Vendor
documentation establishes published capabilities and constraints; it does not
establish this application's compatibility, service latency, realized capacity,
security configuration or total cost. “Unknown” means no suitable product test
or accepted target exists. None of these rows is an accepted runtime decision.

| Candidate | SQL and input/snapshot binding | Identity, isolation and resource controls | Lifecycle, results and pagination | Data movement, latency, operations and cost |
|---|---|---|---|---|
| **Current local DuckDB + Docker** | Same pinned DuckDB engine and broad SQL contract as today. Controller chooses the authorized immutable generation and stages only its approved Parquet. A single exact-directory bind is a proposed experiment; currently the worker receives per-file binds. | Application role checks remain authoritative. DuckDB configuration is not a sandbox by itself; keep SQL in a separately isolated worker. Docker read-only bind mounts and container resource controls are available, but must be applied and tested. The observed 549-file launch rejection is mount-argument metadata overhead, not compute saturation. | Existing synchronous HTTP/busy behavior, ten-second SQL limit, retained result, and exact continuation semantics remain local responsibilities. Docker does not supply request admission, retained result storage, pagination, or uncertain-worker ownership policy. | Inputs are copied/verified locally and bind-mount metadata grows with file count today; a directory bind may reduce mount count but not hashing, verification, copy, I/O or DuckDB costs. Query latency, aggregate capacity and API/refresh headroom are unmeasured. Host, disk, daemon, image, quota, recovery, patching and on-call work remain ours; costs are host/storage/operations, not benchmarked. |
| **Amazon Athena** | Athena queries supported table formats over S3 using Athena's SQL contract: DDL is substantially HiveQL-based and DML is Trino-based, with documented differences and limitations from DuckDB. A generation-specific immutable S3 prefix/table could bind a snapshot, but catalog/table registration and enforcement are product work; querying a moving prefix would not preserve the selected generation. | AWS IAM/workgroups and S3 permissions become part of authorization. Keep the application’s current-role check before starting and before exposing results; do not equate a workgroup grant with the existing application role matrix. Service-managed execution replaces the local worker but adds AWS data-plane access and service identity. Workgroups expose access, usage and data-scan controls; AWS quotas still apply. | Athena `StartQueryExecution` returns an execution ID; clients poll status, then fetch results with `GetQueryResults` continuation tokens. That is naturally job-oriented, not the current synchronous ten-second request and one in-memory retained execution. Exact 1,000-row/1-MiB caps, expiry, current-role rechecks and pagination adapter would be application-owned. | Data may be queried in S3 without local staging, but S3 layout/catalog, IAM, result location and output handling must change. Costs include bytes scanned, requests and result storage; per-query/per-workgroup scan controls exist. Query startup/queue time, scan latency, quotas and total spend for this workload are unknown. There is less worker-host operation but more IAM/catalog/workgroup/result-lifecycle ownership. |
| **MotherDuck** | DuckDB-derived SQL is the closest published engine match, but exact pinned-version, extension, parser and result-type compatibility are unverified. MotherDuck publishes queryable database snapshot retention, but that does not by itself bind this application's selected public generation; immutable object paths or a tested snapshot-selection contract would be required. | MotherDuck publishes account/org identities, service accounts, preset/custom roles on paid tiers, isolated per-user compute (“Ducklings”), and read-scaling replicas. This is not the app's one-role-per-user policy: map the current authenticated principal and authorize each request in the application. Token storage, tenant boundary, cloud data permissions and whether every execution gets the required isolation are product-specific gates. | DuckDB connectivity is documented; exact query cancellation, bounded synchronous HTTP behavior, request-owned execution identity, canonical output, pagination stability and retained-result expiry must be verified. Keep the application wrapper if choosing it; do not expose vendor credentials or raw result access directly to users. | Likely requires making data available to the service or configuring supported cloud access; local path and no-network assumptions do not carry over. Vendor publishes usage-based compute/storage and plan pricing plus read scaling; actual costs depend on plan, compute class, query duration, storage and replicas. Latency, cold start, data-transfer charges, support fit, residency and product contract remain unverified. A paid trial or credential transfer is separately authorized and not part of this phase. |
| **AWS Fargate task per query** | Can retain the DuckDB image/engine and SQL surface, subject to image/platform compatibility. Snapshot pinning remains the controller's job: send generation identity and exact manifest, and make only those verified objects available to the task. | Fargate publishes task-level CPU/memory sizing and a task isolation boundary; task ENI/IAM roles are configurable. This is a stronger managed task boundary than co-located ECS-on-EC2 containers, but task network/IAM settings must still deny unintended access. App roles and exact input authorization remain application-owned. | ECS task start/stop is a remote task lifecycle, not an immediate local process invocation. A request-to-task correlation, polling/cancel behavior, deadlines, durable or bounded retained output, pagination, and cleanup reconciliation must be designed. It may preserve DuckDB result behavior inside the task, but does not automatically preserve the existing HTTP contract. | Local bind mounts cannot cross to Fargate: upload/stage exact inputs to accessible object storage or another supported remote path, then transport results back to the application. Launch/pull/transfer latency is unknown. Cost drivers include vCPU, memory, ephemeral storage, task duration, network/data transfer, logs and supporting AWS resources. Host patching/daemon operation decrease; IAM, networking, task orchestration and cross-system recovery increase. |
| **NsJail on Linux** | Same pinned local DuckDB and SQL behavior can be retained. Controller can continue selecting and staging an immutable local generation; directory delivery still needs the same exact-entry and mutation controls. | NsJail documents namespaces, cgroups, rlimits, read-only mounts and seccomp filters. It removes the Docker daemon from the execution path, not the need for a carefully configured Linux boundary. We own profile correctness, privilege separation, kernel compatibility, aggregate admission, memory/CPU/PID/disk ceilings and lifecycle recovery. | A jailed process can retain the existing synchronous shape, but current result retention/pagination and one-query admission remain application features. The controller must prove process-tree death before releasing resources and input ownership. | Uses local staged files, avoiding remote transfer. No product-specific startup or query latency has been measured; setup/launch advantage is an unverified hypothesis. Costs shift from Docker/daemon administration to Linux host, jail profile/kernel maintenance, quota/admission/recovery engineering and on-call expertise. It does not provide a pool or fair scheduler. |

### Cross-candidate conclusions and unknowns

- **Metadata overhead is separate from execution capacity.** Replacing 549 mounts with one mount may bound Docker mount-argument growth. It cannot establish query speed, staging cost, CPU/memory/disk headroom, or acceptable concurrency. Raising the argument cap alone changes admission but does not remove count growth.
- **Preserve the product contract explicitly.** Every candidate needs the application to bind one authorized immutable snapshot, check current role before execution/result access, and retain one execution's exact result for page continuation without rerunning SQL. Athena's query ID and paginated result API are not equivalent to the current bounded synchronous/result-expiry contract. Remote container services likewise require explicit request ownership and result transport. MotherDuck's DuckDB lineage is promising for dialect compatibility, not proof of end-to-end equivalence.
- **Latency and capacity are unknown for all options.** Product data/query timing distributions, cold/warm setup, preview-vs-heavy SQL contention, busy rates, starvation, S3 transfer and refresh/API overlap have not been measured on representative changed snapshots. Published “serverless,” isolation, read scaling or file-format claims do not substitute for those measurements.
- **A database projection is a distinct optimization hypothesis.** It could reduce per-query file/mount overhead while retaining Parquet as the challenge artifact, but it introduces a second generation-bound artifact and additional refresh/recovery work. The measured blocker is the 549-mount Docker argument bound before container creation; query execution latency has not been measured. A derived database may address mount count, but cannot yet be called the fix or a scalable solution.
- **Operating cost differs rather than disappears.** Local Docker/NsJail retain host, disk, isolation and recovery work; Athena shifts work to data catalog, IAM, workgroups and query/result policy; Fargate shifts it to task orchestration, network/IAM and transport; MotherDuck shifts it to account/token/data-access governance and vendor usage. No total-cost comparison is supportable without owner limits and representative use.

### Primary sources reviewed

- DuckDB warns that untrusted SQL needs an additional sandbox: [security guidance](https://duckdb.org/docs/current/operations_manual/securing_duckdb/overview). Docker documents [bind-mount read-only and recursive behavior](https://docs.docker.com/engine/storage/bind-mounts/) and [container resource constraints](https://docs.docker.com/engine/containers/resource_constraints/).
- DuckDB documents [persistent database files](https://duckdb.org/docs/current/connect/overview), [CTAS/parquet import](https://duckdb.org/docs/lts/data/parquet/overview), and that [multiple processes can read a database only in read-only mode](https://duckdb.org/docs/lts/connect/concurrency). These facts support technical feasibility, not application-level authorization, generation safety, or a performance claim.
- AWS documents Athena's [SQL contract](https://docs.aws.amazon.com/athena/latest/ug/ddl-sql-reference.html), [engine 3 behavior and limitations](https://docs.aws.amazon.com/athena/latest/ug/engine-versions-reference-0003.html), [query start/poll/result flow](https://docs.aws.amazon.com/athena/latest/ug/start-query-execution.html), [paged results](https://docs.aws.amazon.com/athena/latest/APIReference/API_GetQueryResults.html), [workgroup access/cost controls](https://docs.aws.amazon.com/athena/latest/ug/workgroups-manage-queries-control-costs.html), and [data scanned pricing](https://aws.amazon.com/athena/pricing/).
- AWS documents [Fargate task sizing/network/storage constraints](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-tasks-services.html), [task IAM and isolation distinctions](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html), and [task network interfaces](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html). Those docs do not establish Outage Explorer launch latency or end-to-end isolation configuration.
- MotherDuck publishes [hypertenancy](https://motherduck.com/product/hypertenancy/), [read scaling](https://motherduck.com/blog/read-scaling-preview/), and [plans and usage pricing](https://motherduck.com/product/pricing/). The vendor's documentation endpoint for detailed authentication was inaccessible during this review, so no token-scope or authentication behavior beyond the cited product material is treated as verified. The exact current plan, service contract, data path, cancellation and product-specific cost require verification before any trial.
- NsJail's [project documentation](https://github.com/google/nsjail) lists its Linux namespace, cgroup, rlimit, mount and seccomp mechanisms. It does not supply application admission, quota ownership or recovery policy.

## Outcome
Blind authors independently converged on a Docker+DuckDB **evaluation baseline** with one sealed request-directory mount and fixed bounded slots, conditional on measurements. They converged that an argument-cap increase alone is diagnostic and insufficient for count growth, and that a managed service must win on documented product fit/operations rather than assumption. Round 1 objections resulted in tighter directory, aggregate host/storage, daemon-wide recovery and comparison-before-pool gates; author responses are preserved in [decisions](03-decisions.md). The remaining user thresholds are explicit in the spec/open decisions. No runtime/service, ext4-per-lane design, capacity or API enablement is accepted.

Round 2 accepted the workload/SLO/operator-cost pre-experiment gate and an evidence-applicability matrix. There are no remaining blocking objections to this **planning document**. No readiness claim or implementation authorization follows from council convergence.

Both authors explicitly conceded the delivery review's late Round 2 objections; the response is recorded in D6. Remaining owner thresholds keep capacity **undetermined** until supplied and are a gate on experiments/production claims, not a hidden assumption in this draft.

The Parquet-authoritative DuckDB serving-file candidate above was added after
the original blind proposal round in response to the owner's query-latency
question. It is not part of that original convergence or an accepted choice;
D9 records the comparative recommendation and additional gates.
