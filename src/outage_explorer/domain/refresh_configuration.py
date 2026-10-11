"""Declarative constraints for an immutable admitted refresh configuration."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

INITIAL_START = date(2026, 4, 2)
INITIAL_END = date(2026, 10, 1)

PositiveInteger = Annotated[int, Field(strict=True, gt=0)]
S3WorkerCount = Annotated[int, Field(strict=True, ge=1, le=3)]


class RefreshConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    start: date
    end: date
    max_interval_days: PositiveInteger
    source_interval_days: PositiveInteger
    model_interval_days: PositiveInteger
    candidate_seconds: PositiveInteger
    persistence_seconds: PositiveInteger
    contract_version: Literal["v1"] = "v1"
    s3_workers: S3WorkerCount = 3

    @model_validator(mode="after")
    def date_range_fits_limits(self) -> Self:
        if self.start > self.end:
            raise ValueError("Refresh start date must not be after end date")

        inclusive_days = (self.end - self.start).days + 1
        if inclusive_days > self.max_interval_days:
            raise ValueError("Refresh date range exceeds max_interval_days")
        if inclusive_days > self.source_interval_days:
            raise ValueError("Refresh date range exceeds source_interval_days")
        if inclusive_days > self.model_interval_days:
            raise ValueError("Refresh date range exceeds model_interval_days")
        return self

    def validate_initial_load_dates(self) -> None:
        """Require the agreed date range for a first publication."""
        if self.start != INITIAL_START or self.end != INITIAL_END:
            raise ValueError(
                f"Initial refresh must cover {INITIAL_START} through {INITIAL_END}"
            )
