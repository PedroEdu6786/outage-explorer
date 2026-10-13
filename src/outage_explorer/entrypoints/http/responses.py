"""Reusable response DTO contract and Flask serialization decorator."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Protocol, Self

from flask import Response, jsonify


@dataclass(frozen=True)
class ResponseData:
    body: object
    status: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)


class ResponseDTO(Protocol):
    @classmethod
    def from_result(cls, result: Any) -> Self: ...

    def build(self) -> ResponseData: ...


def respond_with(
    response_dto: type[ResponseDTO],
) -> Callable[[Callable[..., object]], Callable[..., Response]]:
    """Map one handler result through its DTO and serialize one HTTP response.

    Place inside access/input guards so they run before the handler. Exceptions
    propagate to the existing error handlers; shared response finalizers still run.
    """

    def decorate(handler: Callable[..., object]) -> Callable[..., Response]:
        @wraps(handler)
        def responded(*args: object, **kwargs: object) -> Response:
            result = handler(*args, **kwargs)
            data = response_dto.from_result(result).build()
            response = jsonify(data.body)
            response.status_code = data.status
            response.headers.update(data.headers)
            return response

        return responded

    return decorate


@dataclass(frozen=True)
class JsonPayloadResponse:
    """Render an already-public application payload without adding an envelope."""

    body: dict[str, object]

    @classmethod
    def from_result(cls, result: dict[str, object]) -> Self:
        return cls(body=result)

    def build(self) -> ResponseData:
        return ResponseData(body=self.body)
