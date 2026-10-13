from dataclasses import dataclass
from typing import Self

import pytest
from flask import Flask

from outage_explorer.entrypoints.http.responses import ResponseData, respond_with


@dataclass
class NamesResponse:
    names: list[str]

    @classmethod
    def from_result(cls, result: list[dict[str, str]]) -> Self:
        return cls([item["name"] for item in result])

    def build(self) -> ResponseData:
        return ResponseData(body=self.names)


def test_response_decorator_supports_other_dtos_and_preserves_handler_arguments():
    app = Flask(__name__)
    calls = []

    @respond_with(NamesResponse)
    def names(prefix: str, *, suffix: str) -> list[dict[str, str]]:
        calls.append((prefix, suffix))
        return [{"name": prefix + suffix, "private": "not-for-the-client"}]

    with app.app_context():
        response = names("hello", suffix="world")

    assert response.status_code == 200
    assert response.get_json() == ["helloworld"]
    assert response.mimetype == "application/json"
    assert calls == [("hello", "world")]
    assert names.__name__ == "names"


@pytest.mark.parametrize("fail_mapping", [False, True])
def test_response_decorator_preserves_exception_handling(fail_mapping):
    app = Flask(__name__)

    class FailingResponse(NamesResponse):
        @classmethod
        def from_result(cls, result: list[dict[str, str]]) -> Self:
            raise ValueError("mapping failed")

    @app.errorhandler(ValueError)
    def error_response(error):
        return {"error": "handled"}, 422

    @app.get("/names")
    @respond_with(FailingResponse if fail_mapping else NamesResponse)
    def names():
        if not fail_mapping:
            raise ValueError("handler failed")
        return []

    response = app.test_client().get("/names")
    assert response.status_code == 422
    assert response.json == {"error": "handled"}
