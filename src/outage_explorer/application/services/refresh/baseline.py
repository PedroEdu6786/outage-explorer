"""Restore and verify the generation pinned by an admitted refresh."""

from collections.abc import Callable

from outage_explorer.application.dto import ResourceRequest
from outage_explorer.application.errors import StaleRefreshOwnerError
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.application.ports.candidates import ResourceBaseline
from outage_explorer.application.ports.connector import DurableResourceReceipt
from outage_explorer.application.ports.publication import ResourcePublicationStore
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.publication import (
    RefreshRun,
    ResourcePublishedGeneration,
)
from outage_explorer.domain.refresh import Interval, RefreshBounds


def _restore_receipt(
    base: ResourcePublishedGeneration, base_run: RefreshRun
) -> DurableResourceReceipt:
    resources = tuple(
        ArtifactRef(
            StoredObject(
                item.object_key or "", item.sha256 or "", item.byte_count or 0
            ),
            "resource",
            item.grain.value,
            None,
            item.rows,
        )
        for item in base.datasets
    )
    return DurableResourceReceipt(
        base.id,
        resources,
        Interval(base_run.configuration.start, base_run.configuration.end),
        ResourceRequest.contract_id,
        ResourceRequest.transformation_id,
        base.base_generation_id,
    )


def _resource_identities(
    resources: tuple[ArtifactRef, ...],
) -> tuple[tuple[Grain, str, int, int], ...]:
    return tuple(
        (ref.grain, ref.object.sha256, ref.object.byte_count, ref.row_count)
        for ref in resources
    )


def _require_restored_identity(
    restored: ResourceBaseline, receipt: DurableResourceReceipt
) -> None:
    if (
        restored.generation_id != receipt.generation_id
        or restored.contract_id != receipt.contract_id
        or restored.transformation_id != receipt.transformation_id
        or _resource_identities(restored.resources)
        != _resource_identities(receipt.resources)
    ):
        raise ArtifactError("Pinned base identity mismatch")


class RestoreRefreshBaseline:
    def __init__(
        self,
        store: RefreshStore,
        publication: ResourcePublicationStore,
        restore: Callable[[DurableResourceReceipt, RefreshBounds], ResourceBaseline],
        bounds: RefreshBounds,
    ) -> None:
        self._store = store
        self._publication = publication
        self._restore = restore
        self._bounds = bounds

    def restore(self, run: RefreshRun) -> ResourceBaseline | None:
        base = self._publication.active_generation()
        if (None if base is None else base.id) != run.base_generation_id:
            raise StaleRefreshOwnerError("Pinned base changed")
        if base is None:
            return None

        base_run = self._store.get_run(base.run_id)
        if base_run is None or base_run.generation_id != base.id:
            raise ArtifactError("Pinned base run identity mismatch")
        receipt = _restore_receipt(base, base_run)
        restored = self._restore(receipt, self._bounds)
        _require_restored_identity(restored, receipt)
        return restored
