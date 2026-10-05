import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest

from outage_explorer.domain.datasets import Column, ValueType
from outage_explorer.infrastructure.query_results.duckdb_types import value_type
from outage_explorer.infrastructure.query_results.encoding import (
    EncodingBounds,
    EncodingLimit,
    UnsupportedValue,
    canonical_json,
    encode_cell,
    retain_result,
)

BOUNDS = EncodingBounds(1_048_576, 16, 10000, 100, 65536)
COLUMNS = [Column("x", ValueType("integer"))]


def test_exact_row_boundary_and_only_one_lookahead():
    consumed = []

    def rows():
        for n in range(2000):
            consumed.append(n)
            yield [n]

    result = retain_result(COLUMNS, rows(), BOUNDS)
    assert consumed == list(range(1001))
    assert result.retained_row_count == 1000
    assert result.truncation_reason == "row_limit"
    assert len(result.document) < 1048576
    exact = retain_result(COLUMNS, ([n] for n in range(1000)), BOUNDS)
    assert exact.retained_row_count == 1000 and exact.truncation_reason is None


def test_utf8_escaping_complete_prefix_and_never_skip_oversized_row():
    columns = [Column("é", ValueType("string"))]
    result = retain_result(
        columns, [['é\n"'], ["x" * 600], ["fits"]], BOUNDS, max_bytes=500
    )
    data = json.loads(result.document)
    assert data["rows"] == [['é\n"']]
    assert result.truncation_reason == "byte_limit"
    assert len(result.document) <= 500
    assert b"\xc3\xa9" in result.document
    assert b"\\n" in result.document
    assert result.document == canonical_json(data)


def test_oversized_first_row_differs_from_empty_result_and_schema_failure():
    columns = [Column("x", ValueType("string"))]
    empty = retain_result(columns, [], BOUNDS, max_bytes=500)
    first = retain_result(columns, [["x" * 1000]], BOUNDS, max_bytes=500)
    assert first.retained_row_count == empty.retained_row_count == 0
    assert first.truncation_reason == "byte_limit" and empty.truncation_reason is None
    with pytest.raises(EncodingLimit):
        retain_result(columns, [], BOUNDS, max_bytes=10)


def test_one_mib_includes_schema_and_metadata_and_stops_before_nonfitting_row():
    result = retain_result(
        [Column("x", ValueType("string"))],
        [["x" * 1048100], ["z" * 1000], ["tiny"]],
        BOUNDS,
    )
    assert result.retained_row_count == 1 and result.truncation_reason == "byte_limit"
    assert len(result.document) <= 1048576
    assert json.loads(result.document)["rows"] == [["x" * 1048100]]


def test_duplicate_labels_precise_values_and_nullability():
    columns = [
        Column("x", ValueType("integer")),
        Column("x", ValueType("decimal", 38, 12)),
        Column("missing", ValueType("string"), None),
    ]
    result = json.loads(
        retain_result(
            columns, [[9007199254740993, Decimal("0.123456789012"), None]], BOUNDS
        ).document
    )
    assert [c["name"] for c in result["columns"]] == ["x", "x", "missing"]
    assert result["rows"] == [["9007199254740993", "0.123456789012", None]]
    with pytest.raises(UnsupportedValue):
        retain_result(COLUMNS, [[None]], BOUNDS)
    with pytest.raises(UnsupportedValue):
        retain_result(COLUMNS, [[1, 2]], BOUNDS)


def test_cumulative_nested_cell_bytes_and_depth_are_bounded():
    typ = ValueType("list", children=(("child", ValueType("string")),))
    with pytest.raises(EncodingLimit):
        encode_cell(["x" * 60, "y" * 60], typ, replace(BOUNDS, max_cell_bytes=100))
    with pytest.raises(EncodingLimit):
        encode_cell(["a"] * 5, typ, replace(BOUNDS, max_nested_items=3))
    nested = ValueType("list", children=(("child", typ),))
    with pytest.raises(EncodingLimit):
        encode_cell([["a"]], nested, replace(BOUNDS, max_depth=1))


def test_schema_is_bounded_before_descriptor_expansion():
    typ = ValueType("string")
    for _ in range(100):
        typ = ValueType("list", children=(("child", typ),))
    with pytest.raises(EncodingLimit):
        retain_result([Column("deep", typ)], [], BOUNDS)
    with pytest.raises(EncodingLimit):
        retain_result([Column("x" * 70000, ValueType("string"))], [], BOUNDS)
    with pytest.raises(UnsupportedValue):
        retain_result([Column("x", ValueType("decimal", 3, 4))], [], BOUNDS)


@pytest.mark.parametrize("value", [True, 1.0, "1", object()])
def test_no_lossy_fallback(value):
    with pytest.raises(UnsupportedValue):
        encode_cell(value, ValueType("integer"), BOUNDS)


@pytest.mark.parametrize(
    "kind",
    ["bignum", "timestamp_ns", "interval", "union", "variant", "time with time zone"],
)
def test_unverified_engine_types_fail_explicitly(kind):
    class EngineType:
        id = kind

    with pytest.raises(UnsupportedValue):
        value_type(EngineType())


@pytest.mark.parametrize(
    ("item", "kind"),
    [
        (date.min, "date"),
        (date.max, "date"),
        (datetime.min, "timestamp"),
        (datetime.max, "timestamp"),
    ],
)
def test_ambiguous_engine_temporal_extremes_are_never_coerced(item, kind):
    with pytest.raises(UnsupportedValue):
        encode_cell(item, ValueType(kind), BOUNDS)
