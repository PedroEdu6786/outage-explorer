"""Transport shapes are validated without session or role policy."""

import pytest
from flask import Flask

from outage_explorer.application.errors import InvalidRequestError, UnauthenticatedError
from outage_explorer.entrypoints.http.schemas import (
    CallbackQuery,
    LoginQuery,
    callback_query,
    json_object,
    login_query,
    query_fields,
)


def test_typed_query_values_and_defaults():
    app = Flask(__name__)
    with app.test_request_context("/"):
        assert login_query() == LoginQuery("/")
    with app.test_request_context("/?return_to=/dashboard"):
        assert login_query() == LoginQuery("/dashboard")
    with app.test_request_context("/?code=code&state=state"):
        assert callback_query() == CallbackQuery("code", "state")


@pytest.mark.parametrize(
    "query",
    [
        "x=1&x=2",
        "unknown=SECRET",
        "x=%00",
        "x=%0A",
        "x=%7F",
        "x=%E2%98%83",
        "x=" + "a" * 4097,
    ],
)
def test_duplicate_unsupported_or_malformed_query(query):
    with Flask(__name__).test_request_context("/?" + query):
        with pytest.raises(InvalidRequestError, match="^Invalid request$"):
            query_fields(frozenset({"x"}))


def test_required_query_and_generic_provider_error():
    app = Flask(__name__)
    with app.test_request_context("/"):
        with pytest.raises(InvalidRequestError):
            query_fields(frozenset({"x"}), required=frozenset({"x"}))
    with app.test_request_context("/?error=SECRET&error_description=SECRET"):
        with pytest.raises(UnauthenticatedError, match="^Login failed$"):
            callback_query()


def test_plain_json_object_and_required_keys():
    with Flask(__name__).test_request_context(
        "/", method="POST", json={"label": "sample", "count": 2}
    ):
        assert json_object(
            frozenset({"label", "count"}), required=frozenset({"count"})
        ) == {"label": "sample", "count": 2}


@pytest.mark.parametrize(
    "body,content_type",
    [
        ('{"label":"SECRET"}', "text/plain"),
        ("", "application/json"),
        ("null", "application/json"),
        ("[]", "application/json"),
        ('{"label":', "application/json"),
        ('{"label":1,"label":2}', "application/json"),
        ('{"label":{"x":1,"x":2}}', "application/json"),
        ('{"other":"SECRET"}', "application/json"),
        ('{"label":NaN}', "application/json"),
        ('{"label":Infinity}', "application/json"),
        (b'{"label":"\xff"}', "application/json"),
        ('{"label":"' + "a" * 65536 + '"}', "application/json"),
        ("{}", "application/json"),
    ],
)
def test_malformed_duplicate_unsupported_json(body, content_type):
    with Flask(__name__).test_request_context(
        "/", method="POST", data=body, content_type=content_type
    ):
        with pytest.raises(InvalidRequestError, match="^Invalid request$"):
            json_object(frozenset({"label"}), required=frozenset({"label"}))
