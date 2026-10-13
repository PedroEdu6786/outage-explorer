"""Product refresh admission configuration."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class RefreshSettings:
    """Nonsecret startup snapshot; starting limits are not measured budgets."""

    start_date: date
    candidate_seconds: int = 1800
    persistence_seconds: int = 1800
    s3_workers: int = 3

    def __post_init__(self) -> None:
        limits = (
            self.candidate_seconds,
            self.persistence_seconds,
        )
        if (
            any(type(value) is not int or value <= 0 for value in limits)
            or type(self.s3_workers) is not int
            or not 1 <= self.s3_workers <= 3
        ):
            raise ValueError("Invalid refresh configuration")


def refresh_settings(environment: Mapping[str, str]) -> RefreshSettings:
    """Snapshot the strict ISO start and budgets; end is resolved at admission."""
    try:
        start = environment["OUTAGE_REFRESH_START_DATE"]
        first = date.fromisoformat(start)
        if first.isoformat() != start:
            raise ValueError
        values = [
            int(environment.get(name, str(default)))
            for name, default in (
                ("OUTAGE_REFRESH_CANDIDATE_SECONDS", 1800),
                ("OUTAGE_REFRESH_PERSISTENCE_SECONDS", 1800),
                ("OUTAGE_REFRESH_S3_WORKERS", 3),
            )
        ]
        result = RefreshSettings(first, *values)
        return result
    except (KeyError, ValueError, TypeError, OverflowError):
        raise ValueError("Invalid refresh configuration") from None
