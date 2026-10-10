"""Restore and verify the generation pinned by an admitted refresh."""

from collections.abc import Callable

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
from outage_explorer.domain.publication import RefreshRun
from outage_explorer.domain.refresh import Interval, RefreshBounds


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
        descriptors = tuple(
            ArtifactRef(
                StoredObject(
                    item.object_key or "",
                    item.sha256 or "",
                    item.byte_count or 0,
                ),
                "resource",
                item.grain.value,
                None,
                item.rows,
            )
            for item in base.datasets
        )
        prior = self._restore(
            DurableResourceReceipt(
                base.id,
                descriptors,
                Interval(base_run.configuration.start, base_run.configuration.end),
                "eia-nuclear-observations-v1",
                "outage-share-exact-v1",
                base.base_generation_id,
            ),
            self._bounds,
        )
        if (
            prior.generation_id != base.id
            or prior.contract_id != "eia-nuclear-observations-v1"
            or prior.transformation_id != "outage-share-exact-v1"
            or tuple(
                (r.grain, r.object.sha256, r.object.byte_count, r.row_count)
                for r in prior.resources
            )
            != tuple(
                (r.grain, r.object.sha256, r.object.byte_count, r.row_count)
                for r in descriptors
            )
        ):
            raise ArtifactError("Pinned base identity mismatch")
        return prior
