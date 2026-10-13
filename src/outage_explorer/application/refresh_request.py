"""Immutable admission inputs shared by HTTP and direct refresh callers."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from outage_explorer.application.errors import InvalidRequestError


class RefreshAdmissionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    idempotency_key: str = Field(
        min_length=16, max_length=128, pattern=r"\A[A-Za-z0-9_-]+\z"
    )

    @classmethod
    def parse(cls, **values: object) -> Self:
        try:
            return cls.model_validate(values)
        except ValidationError:
            raise InvalidRequestError("Invalid refresh request") from None
