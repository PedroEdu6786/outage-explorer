"""Pure rules for publishing a candidate against its admitted baseline."""

from outage_explorer.domain.publication import (
    RefreshConfiguration,
    RefreshRun,
    ResourcePublishedGeneration,
    RunStatus,
)


class PublicationBaseChangedError(ValueError):
    """The active generation no longer matches the admitted and candidate base."""


class RefreshAdmissionSlotBusyError(ValueError):
    """A different refresh already owns the admission slot."""


def replay_or_require_available(
    existing_run: RefreshRun | None, active_run_id: str | None
) -> RefreshRun | None:
    """Replay the same request before rejecting a slot owned by another run."""
    if existing_run is not None:
        return existing_run
    if active_run_id is not None:
        raise RefreshAdmissionSlotBusyError("Refresh already admitted")
    return None


def require_initial_load_start(
    configuration: RefreshConfiguration, base_generation_id: str | None
) -> None:
    if base_generation_id is None:
        configuration.validate_initial_load_start_date()


def require_publishable_base(
    run: RefreshRun,
    generation: ResourcePublishedGeneration,
    active_generation_id: str | None,
) -> None:
    if (
        active_generation_id != run.base_generation_id
        or active_generation_id != generation.base_generation_id
    ):
        raise PublicationBaseChangedError("Publication base changed")
    require_initial_load_start(run.configuration, active_generation_id)


def should_interrupt_unpublished_run(
    run: RefreshRun,
    *,
    is_active_run: bool,
    lease_is_healthy: bool | None,
    force: bool,
) -> bool:
    return (
        is_active_run
        and run.status in {RunStatus.RUNNING, RunStatus.PUBLICATION_UNKNOWN}
        and (force or not lease_is_healthy)
    )
