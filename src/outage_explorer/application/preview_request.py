"""Immutable preview inputs shared by HTTP and direct application callers."""

from datetime import date
from typing import Self

from pydantic import Field, field_validator, model_validator

from outage_explorer.application.errors import InvalidRequestError
from outage_explorer.application.pagination.request import CursorPaginationRequest
from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.preview_filters import validate_facility_identifier


class PreviewRequest(CursorPaginationRequest):
    start: date | None = None
    end: date | None = None
    facility: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("facility")
    @classmethod
    def exact_facility(cls, value: str | None) -> str | None:
        return None if value is None else validate_facility_identifier(value)

    @model_validator(mode="after")
    def valid_selection(self) -> Self:
        if self.cursor is not None and any(
            value is not None
            for value in (self.start, self.end, self.size, self.facility)
        ):
            raise ValueError("Continuation accepts only its cursor")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("Start date must not follow end date")
        return self

    def validate_dataset(self, dataset: Dataset) -> None:
        if self.facility is not None and dataset.grain == "national":
            raise InvalidRequestError("National preview does not support facility")
