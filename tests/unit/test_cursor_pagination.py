"""Shared pagination works with independent row/key types and endpoint metadata."""

import json
from dataclasses import replace
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    InvalidRequestError,
)
from outage_explorer.application.pagination.cursor import CursorPage, CursorPaginator
from outage_explorer.application.pagination.request import CursorPaginationRequest
from outage_explorer.application.preview_request import PreviewRequest


def byte_count(value):
    return len(json.dumps(value, ensure_ascii=False).encode())


@pytest.mark.parametrize(
    ("rows", "keys", "metadata"),
    [
        (({"name": "one"}, {"name": "two"}), (10, 20), {"collection": "items"}),
        ((["é", "01"], ["😀", "02"]), (("01",), ("02",)), {"columns": ["a", "b"]}),
    ],
)
def test_reusable_page_types_and_last_returned_key(rows, keys, metadata):
    page = CursorPage(rows, keys, True, 2, None, lambda key: str(key), metadata)
    complete = CursorPaginator(byte_count, response_bytes=10000).paginate(page)
    paginator = CursorPaginator(byte_count, response_bytes=byte_count(complete) - 1)
    response = paginator.paginate(page)
    assert response["rows"] == [rows[0]]
    assert response["has_more"] is True
    assert response["next_cursor"] == str(keys[0])
    assert response["page_cursor"] == "None"
    assert all(response[key] == value for key, value in metadata.items())
    assert byte_count(response) <= byte_count(complete) - 1


def test_empty_final_and_oversized_pages():
    paginator = CursorPaginator(byte_count, response_bytes=1000)
    empty = CursorPage((), (), False, 100, None, lambda key: "current", {})
    response = paginator.paginate(empty)
    assert response["rows"] == [] and response["next_cursor"] is None
    assert response["has_more"] is False
    final = replace(empty, rows=("last",), keys=(1,))
    assert paginator.paginate(final)["next_cursor"] is None
    with pytest.raises(AnalyticalResourceError):
        CursorPaginator(byte_count, response_bytes=1).paginate(empty)
    with pytest.raises(AnalyticalResourceError):
        CursorPaginator(byte_count, response_bytes=1).paginate(final)


@pytest.mark.parametrize(
    ("rows", "keys", "has_more", "size"),
    [(("a",), (), False, 1), (("a", "b"), (1, 2), False, 1), ((), (), True, 1)],
)
def test_invalid_read_cannot_make_a_cursor(rows, keys, has_more, size):
    def cursor(key):
        pytest.fail("Invalid output must fail before making cursors")

    with pytest.raises(AnalyticalResourceError):
        CursorPaginator(byte_count, response_bytes=1000).paginate(
            CursorPage(rows, keys, has_more, size, None, cursor, {})
        )


@pytest.mark.parametrize(
    "values",
    [
        {"size": True},
        {"size": "100"},
        {"size": 0},
        {"size": 501},
        {"cursor": ""},
        {"cursor": "x", "size": 1},
        {"unknown": 1},
    ],
)
def test_shared_request_rejects_invalid_inputs(values):
    with pytest.raises(InvalidRequestError):
        CursorPaginationRequest.parse(**values)


@pytest.mark.parametrize(
    "values",
    [
        {"start": "2026-01-01"},
        {"start": datetime(2026, 1, 1)},
        {"start": date(2026, 2, 1), "end": date(2026, 1, 1)},
        {"cursor": "x", "facility": "001"},
        {"cursor": "x", "start": date(2026, 1, 1)},
        {"facility": "é" * 129},
        {"facility": " 001"},
        {"facility": "\ud800"},
    ],
)
def test_preview_adds_filter_validation(values):
    with pytest.raises(InvalidRequestError):
        PreviewRequest.parse(**values)


def test_request_is_frozen_and_preserves_identifier():
    request = PreviewRequest.parse(facility="001")
    assert request.facility == "001" and request.page_size == 100
    with pytest.raises(ValidationError):
        request.size = 5
