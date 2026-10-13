"""Pydantic HTTP query DTOs; SQL inspection remains in its isolated service."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from outage_explorer.application.errors import InvalidRequestError


class QueryRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    page: int = Field(ge=1, le=2147483647)

    @classmethod
    def parse(cls, **values: object) -> Self:
        try:
            return cls.model_validate(values)
        except ValidationError:
            raise InvalidRequestError("Invalid request") from None


class QuerySubmissionRequest(QueryRequest):
    sql: str
    page_size: int = Field(ge=1, le=500)

    @field_validator("sql")
    @classmethod
    def bounded_sql(cls, value: str) -> str:
        if not value.strip() or len(value.encode("utf-8")) > 65536:
            raise ValueError("Invalid SQL input")
        return value


class QueryPageRequest(QueryRequest):
    query_id: str = Field(min_length=1)
    page_size: int | None = Field(default=None, ge=1, le=500)

    @field_validator("query_id")
    @classmethod
    def bounded_identifier(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 4096:
            raise ValueError("Invalid query identifier")
        return value
