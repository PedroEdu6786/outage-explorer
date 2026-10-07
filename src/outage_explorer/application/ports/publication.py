"""Short atomic publication and immutable history lookup boundaries."""

from typing import Protocol

from outage_explorer.domain.publication import (
    RefreshOwner,
    RefreshRun,
    ResourcePublishedGeneration,
)


class ResourcePublicationStore(Protocol):
    """Descriptor-only publication seam, prepared before the shared cutover.

    Implementations validate the complete resource contract and preserve atomic
    owner/epoch/lease/base fences, immutable history and uncertain-commit recovery.
    No existing PostgreSQL schema or adapter is implied by this declaration.
    """

    def active_generation(self) -> ResourcePublishedGeneration | None: ...
    def generation_for_run(self, run_id: str) -> ResourcePublishedGeneration | None: ...
    def publish(
        self,
        owner: RefreshOwner,
        generation: ResourcePublishedGeneration,
        quality_json: str | None = None,
    ) -> RefreshRun: ...
