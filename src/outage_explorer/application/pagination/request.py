"""Common strict inputs for endpoints using cursor pagination."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from outage_explorer.application.errors import InvalidRequestError


class CursorPaginationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    size: int | None = Field(default=None, ge=1, le=500)
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def fixed_continuation_size(self) -> Self:
        if self.cursor is not None and self.size is not None:
            raise ValueError("Continuation cannot change page size")
        return self

    @property
    def page_size(self) -> int:
        return 100 if self.size is None else self.size

    @classmethod
    def parse(cls, **values: object) -> Self:
        try:
            return cls.model_validate(values)
        except ValidationError:
            raise InvalidRequestError("Invalid request parameters") from None
