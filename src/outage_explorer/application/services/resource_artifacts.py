"""Explicit three-file durability and recovery, without publication authority."""

from functools import partial

from outage_explorer.application.ports.artifacts import ArtifactError, ArtifactRef
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    ResourceBaseline,
)
from outage_explorer.application.ports.connector import (
    DurableResourceReceipt,
    ResourceFiles,
    ResourceTransfers,
)
from outage_explorer.application.ports.connector_workers import ConnectorWorkers
from outage_explorer.domain.refresh import RefreshBounds


class PersistResourceArtifacts:
    def __init__(
        self,
        local: ResourceFiles,
        durable: ResourceTransfers,
        workers: ConnectorWorkers | None = None,
    ) -> None:
        self.local, self.durable, self.workers = local, durable, workers

    def execute(
        self, candidate: CandidateResult, bounds: RefreshBounds
    ) -> DurableResourceReceipt:
        if candidate.outcome != "candidate":
            raise ArtifactError("Retained outcome cannot create a durable generation")
        self.local.verify_candidate(candidate, bounds)
        addresses = self.durable.addresses(candidate.generation_id, candidate.resources)
        tasks = tuple(
            partial(self._transfer, local, remote)
            for local, remote in zip(candidate.resources, addresses, strict=True)
        )
        if self.workers is None:
            results = tuple(task() for task in tasks)
        else:
            results = self.workers.run(tasks)
        if tuple(results) != addresses:
            raise ArtifactError("Durable resource descriptors differ from candidate")
        return DurableResourceReceipt(
            candidate.generation_id,
            addresses,
            candidate.interval,
            candidate.contract_id,
            candidate.transformation_id,
            candidate.base_generation_id,
            candidate.schema_version,
        )

    def _transfer(self, local: ArtifactRef, remote: ArtifactRef) -> ArtifactRef:
        chunks = self.local.read(local.object)
        try:
            return self.durable.put_verified(remote, chunks)
        finally:
            close = getattr(chunks, "close", None)
            if close is not None:
                close()


class RecoverResourceArtifacts:
    def __init__(self, local: ResourceFiles, durable: ResourceTransfers) -> None:
        self.local, self.durable = local, durable

    def execute(
        self, receipt: DurableResourceReceipt, bounds: RefreshBounds
    ) -> ResourceBaseline:
        self.durable.validate_receipt(receipt)
        return self.local.restore_resources(receipt, self.durable, bounds)
