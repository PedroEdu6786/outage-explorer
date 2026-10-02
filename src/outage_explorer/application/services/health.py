from outage_explorer.application.dto import HealthStatus
from outage_explorer.application.ports.clock import Clock


class HealthService:
    """Report process liveness, without probing external dependencies."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def check(self) -> HealthStatus:
        return HealthStatus(checked_at=self._clock.now())
