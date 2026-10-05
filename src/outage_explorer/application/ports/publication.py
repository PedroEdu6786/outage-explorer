"""Short atomic publication and immutable history lookup boundaries."""

from typing import Protocol

from outage_explorer.domain.publication import (
    PublishedGeneration,
    RefreshOwner,
    RefreshRun,
)


class PublicationStore(Protocol):
    def active_generation(self) -> PublishedGeneration | None: ...
    def generation_for_run(self, run_id: str) -> PublishedGeneration | None: ...
    def publish(
        self,
        owner: RefreshOwner,
        generation: PublishedGeneration,
        quality_json: str | None = None,
    ) -> RefreshRun: ...
