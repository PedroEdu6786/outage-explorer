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

## Managed and other alternatives considered by the authors
| Alternative | Value to evaluate | Contract/operating cost to resolve |
|---|---|---|
| Separate bounded Docker argv allowance | Small diagnostic unblock for the existing layout | Mount count still grows with files; no concurrency solution |
| Fargate managed tasks | Transfers host/container infrastructure management while retaining DuckDB | Remote input/result transport, task ownership/cancellation, launch latency, network/IAM and cost; current local file binds cannot simply move remotely |
| Athena | Managed SQL directly over S3 with service-side capacity | Different dialect/types, async/queued lifecycle, immutable snapshot addressing, authorization, result encoding/retention and cancellation; current local-cache/no-network boundary changes |
| MotherDuck | Managed DuckDB-based execution and documented account-specific compute/read scaling | Pinned compatibility, credential/account scope, local-versus-cloud execution, snapshot visibility, cancellation, result contract and spend must be verified |
| NsJail / OS sandbox | Alternative isolation without Docker daemon control | Application still owns Linux isolation, quotas, termination, staging and recovery; startup advantage remains unmeasured |

Primary-source links and evidence limitations are in [the problem anchor](00-problem.md#primary-source-reconnaissance).

## Outcome
Blind authors independently converged on a Docker+DuckDB **evaluation baseline** with one sealed request-directory mount and fixed bounded slots, conditional on measurements. They converged that an argument-cap increase alone is diagnostic and insufficient for count growth, and that a managed service must win on documented product fit/operations rather than assumption. Round 1 objections resulted in tighter directory, aggregate host/storage, daemon-wide recovery and comparison-before-pool gates; author responses are preserved in [decisions](03-decisions.md). The remaining user thresholds are explicit in the spec/open decisions. No runtime/service, ext4-per-lane design, capacity or API enablement is accepted.

Round 2 accepted the workload/SLO/operator-cost pre-experiment gate and an evidence-applicability matrix. There are no remaining blocking objections to this **planning document**. No readiness claim or implementation authorization follows from council convergence.

Both authors explicitly conceded the delivery review's late Round 2 objections; the response is recorded in D6. Remaining owner thresholds keep capacity **undetermined** until supplied and are a gate on experiments/production claims, not a hidden assumption in this draft.
