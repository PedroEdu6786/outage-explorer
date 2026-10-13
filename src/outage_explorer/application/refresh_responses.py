"""Public refresh response data without HTTP framework dependencies."""

from dataclasses import dataclass
from typing import Self

from outage_explorer.application.data_payloads import refresh_payload
from outage_explorer.domain.publication import RefreshRun


@dataclass(frozen=True)
class RefreshAdmissionResult:
    run_id: str
    status: str
    start_date: str
    end_date: str
    terminal: bool

    @classmethod
    def from_result(cls, run: RefreshRun) -> Self:
        return cls(
            run_id=run.id,
            status=run.status.value,
            start_date=run.configuration.start.isoformat(),
            end_date=run.configuration.end.isoformat(),
            terminal=run.status.terminal,
        )


@dataclass(frozen=True)
class RefreshRunResult:
    run: dict[str, object] | None

    @classmethod
    def from_result(cls, run: RefreshRun | None) -> Self:
        return cls(run=None if run is None else refresh_payload(run))
