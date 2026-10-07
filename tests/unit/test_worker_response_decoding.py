from datetime import date
from decimal import Decimal

import pytest

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.application.ports.execution import (
    PreviewRead,
    PreviewRows,
    QueryRead,
)
from outage_explorer.application.ports.sql_inspection import SqlRejected
from outage_explorer.domain.datasets import PUBLIC_DATASETS, Column, ValueType
from outage_explorer.infrastructure.query_results.encoding import (
    canonical_json,
    retain_result,
)
from outage_explorer.infrastructure.query_results.preview_encoding import (
    PreviewEncoding,
)
from outage_explorer.infrastructure.sql_validation.inspection import DuckdbSqlInspector
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile
from outage_explorer.infrastructure.worker_runtime.decoding import WorkerTransport
from outage_explorer.infrastructure.worker_runtime.protocol import AnalyticalWorker


@pytest.fixture
def transport():
    return WorkerTransport(
        RuntimeProfile(
            image_id="sha256:" + "a" * 64,
            daemon_endpoint="unix:///var/run/docker.sock",
            platform="synthetic",
            daemon_version="synthetic",
            filesystem_identity="synthetic",
        )
    )


def query_result(transport):
    columns = (
        Column("same", ValueType("integer")),
        Column(
            "same",
            ValueType("list", children=(("child", ValueType("decimal", 38, 12)),)),
        ),
    )
    return retain_result(
        columns, [(42, [Decimal("10.123456789012")])], transport.bounds
    )


def envelope(result):
    import json

    return canonical_json(
        {"version": 1, "operation": "query", "result": json.loads(result.document)}
    )


def test_query_exact_bytes_duplicate_labels_nested_types(transport):
    result = query_result(transport)
    output = transport.decode(
        envelope(result) + b"\n", request=QueryRead("SELECT 42", ()), exit_code=0
    )
    assert output.document == result.document
    assert output.retained_row_count == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(extra=1),
        lambda r: r.update(retained_row_count=True),
        lambda r: r.update(retained_row_count=2),
        lambda r: r.update(truncated=True),
        lambda r: r.update(truncation_reason="row_limit", truncated=True),
        lambda r: r["limits"].update(max_rows=True),
        lambda r: r["columns"][0].update(index=True),
        lambda r: r["columns"][0].update(encoding="number"),
        lambda r: r["columns"][0].update(extra=1),
        lambda r: r["rows"][0].__setitem__(0, "042"),
        lambda r: r["rows"][0].__setitem__(0, 42),
        lambda r: r["rows"][0].__setitem__(0, None),
        lambda r: r["rows"][0].append("extra"),
        lambda r: r["rows"][0].__setitem__(1, ["1e1"]),
    ],
)
def test_query_corruption(transport, mutation):
    import json

    value = json.loads(envelope(query_result(transport)))
    mutation(value["result"])
    with pytest.raises(RuntimeUnavailableError):
        transport.decode(
            canonical_json(value), request=QueryRead("SELECT 42", ()), exit_code=0
        )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"version":1,"version":1}',
        b'{"version":NaN}',
        b"{}{}",
        b"\xff",
        b"[]",
        b"{",
        b'{"version":true}',
        b"x" * 1_179_649,
    ],
)
def test_invalid_transport(transport, raw):
    with pytest.raises(RuntimeUnavailableError):
        transport.decode(raw, request=QueryRead("SELECT 42", ()), exit_code=0)


def test_exact_order_and_canonical_bytes(transport):
    import json

    value = json.loads(envelope(query_result(transport)))
    result = value["result"]
    value["result"] = {k: result[k] for k in reversed(result)}
    with pytest.raises(RuntimeUnavailableError):
        transport.decode(
            canonical_json(value), request=QueryRead("SELECT 42", ()), exit_code=0
        )
    for raw in [
        envelope(query_result(transport)).replace(b'"42"', b'"\\u0034\\u0032"'),
        envelope(query_result(transport)) + b"\n\n",
    ]:
        with pytest.raises(RuntimeUnavailableError):
            transport.decode(raw, request=QueryRead("SELECT 42", ()), exit_code=0)


@pytest.mark.parametrize(
    "code,cls",
    [
        ("unsupported_sql", SqlRejected),
        ("invalid_sql", SqlRejected),
        ("query_resource_limit", AnalyticalResourceError),
        ("data_unavailable", DataUnavailableError),
        ("invalid_request", RuntimeUnavailableError),
        ("unknown", RuntimeUnavailableError),
    ],
)
def test_safe_errors_and_exit_pairing(transport, code, cls):
    raw = canonical_json({"version": 1, "error": {"code": code}})
    with pytest.raises(cls):
        transport.decode(raw, request=QueryRead("SELECT 42", ()), exit_code=1)
    with pytest.raises(RuntimeUnavailableError):
        transport.decode(raw, request=QueryRead("SELECT 42", ()), exit_code=0)
    with pytest.raises(RuntimeUnavailableError):
        transport.decode(
            envelope(query_result(transport)),
            request=QueryRead("SELECT 42", ()),
            exit_code=1,
        )


def preview_fixture(transport):
    dataset = PUBLIC_DATASETS[0]
    row = (
        date(2026, 9, 1),
        Decimal("100.000000000001"),
        Decimal("10"),
        Decimal("10"),
        Decimal("10.00"),
        "1",
        "10",
        "10.00",
        "10.00",
    )
    request = PreviewRead(
        dataset,
        (ApprovedFile("/host/private", "a" * 64, 100, 1),),
        date(2026, 9, 1),
        date(2026, 9, 2),
        None,
        100,
    )
    worker = AnalyticalWorker(
        __import__("pathlib").Path("/inputs"),
        lambda _: PreviewRows((row,), (("2026-09-01",),), False),
        lambda _: None,
        DuckdbSqlInspector(max_sql_bytes=65536, max_nodes=10000, max_depth=64),
        PreviewEncoding(transport.bounds),
    )
    return request, row, worker.execute(transport.request(request))


def test_actual_preview_roundtrip(transport):
    request, row, raw = preview_fixture(transport)
    output = transport.decode(raw, request=request, exit_code=0)
    assert output.rows == (row,)
    assert type(output.rows[0][0]) is date
    assert type(output.rows[0][1]) is Decimal
    assert b"/host/private" not in transport.request(request)


@pytest.mark.parametrize("dataset", PUBLIC_DATASETS)
@pytest.mark.parametrize("fault", [None, "ascending_dates", "duplicate", "cursor"])
def test_preview_newest_first_and_binary_identifiers(transport, dataset, fault):
    from dataclasses import replace

    request, national, _ = preview_fixture(transport)
    identifiers = [
        c.name for c in dataset.columns if c.name in {"facility", "generator"}
    ]
    keys = [("2026-09-02", *("a" for _ in identifiers))]
    if identifiers:
        keys.append(("2026-09-02", *("é" for _ in identifiers)))
    keys.append(("2026-09-01", *("a" for _ in identifiers)))
    if fault == "ascending_dates":
        keys.reverse()
    elif fault == "duplicate":
        keys.append(keys[-1])
    request = replace(
        request, dataset=dataset, after=keys[0] if fault == "cursor" else None
    )
    by_name = {
        column.name: value
        for column, value in zip(PUBLIC_DATASETS[0].columns, national, strict=True)
    }
    rows = []
    for key in keys:
        identity_values = dict(zip(identifiers, key[1:], strict=True))
        rows.append(
            tuple(
                date.fromisoformat(key[0])
                if c.name == "period"
                else identity_values.get(c.name, by_name.get(c.name, "Facility"))
                for c in dataset.columns
            )
        )
    worker = AnalyticalWorker(
        __import__("pathlib").Path("/inputs"),
        lambda _: PreviewRows(tuple(rows), tuple(keys), False),
        lambda _: None,
        DuckdbSqlInspector(max_sql_bytes=65536, max_nodes=10000, max_depth=64),
        PreviewEncoding(transport.bounds),
    )
    raw = worker.execute(transport.request(request))
    if fault:
        with pytest.raises(RuntimeUnavailableError):
            transport.decode(raw, request=request, exit_code=0)
    else:
        output = transport.decode(raw, request=request, exit_code=0)
        assert output.keys == tuple(keys)
        continuation = replace(request, after=keys[0])
        worker._preview = lambda _: PreviewRows(tuple(rows[1:]), tuple(keys[1:]), False)
        result = transport.decode(
            worker.execute(transport.request(continuation)),
            request=continuation,
            exit_code=0,
        )
        assert result.keys == tuple(keys[1:])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["keys"].__setitem__(0, ["2026-09-02"]),
        lambda r: r.update(has_more=1),
        lambda r: r.update(keys=[]),
        lambda r: r["columns"][0].update(nullable=True),
        lambda r: r["rows"][0].__setitem__(0, "20260901"),
        lambda r: r["rows"][0].__setitem__(1, "NaN"),
    ],
)
def test_preview_corruption(transport, mutation):
    import json

    request, _, raw = preview_fixture(transport)
    value = json.loads(raw)
    mutation(value["result"])
    with pytest.raises(RuntimeUnavailableError):
        transport.decode(canonical_json(value), request=request, exit_code=0)


def test_temporal_binary_struct_map_roundtrip(transport):
    from datetime import UTC, datetime, time

    columns = (
        Column("date", ValueType("date")),
        Column("timestamp", ValueType("timestamp_tz")),
        Column("time", ValueType("time")),
        Column("blob", ValueType("binary")),
        Column(
            "struct", ValueType("struct", children=(("number", ValueType("integer")),))
        ),
        Column(
            "map",
            ValueType(
                "map",
                children=(
                    ("key", ValueType("string")),
                    ("value", ValueType("boolean")),
                ),
            ),
        ),
    )
    result = retain_result(
        columns,
        [
            (
                date(2026, 9, 1),
                datetime(2026, 9, 1, tzinfo=UTC),
                time(12, 3, 4),
                b"\x00\xff",
                {"number": 9},
                {"yes": True},
            )
        ],
        transport.bounds,
    )
    assert (
        transport.decode(
            envelope(result), request=QueryRead("SELECT 42", ()), exit_code=0
        ).document
        == result.document
    )


def test_preview_order_after_filters_and_wrong_operation(transport):
    import json
    from dataclasses import replace

    request, _, raw = preview_fixture(transport)
    for changed in [
        replace(request, after=("2026-09-01",)),
        replace(request, start=date(2026, 9, 2)),
    ]:
        with pytest.raises(RuntimeUnavailableError):
            transport.decode(raw, request=changed, exit_code=0)
    value = json.loads(raw)
    value["result"]["rows"] *= 2
    value["result"]["keys"] *= 2
    with pytest.raises(RuntimeUnavailableError):
        transport.decode(canonical_json(value), request=request, exit_code=0)
    value["operation"] = "unknown"
    with pytest.raises(RuntimeUnavailableError):
        transport.decode(canonical_json(value), request=request, exit_code=0)


def test_nested_expansion_and_schema_budget(transport):
    from dataclasses import replace

    bounded = WorkerTransport(replace(transport.profile, json_nodes=10))
    with pytest.raises(RuntimeUnavailableError):
        bounded.decode(
            envelope(query_result(transport)),
            request=QueryRead("SELECT 42", ()),
            exit_code=0,
        )
    import json

    value = json.loads(envelope(query_result(transport)))
    value["result"]["columns"][0]["name"] = "x" * 65_537
    with pytest.raises(RuntimeUnavailableError):
        transport.decode(
            canonical_json(value), request=QueryRead("SELECT 42", ()), exit_code=0
        )


def test_request_rejects_invalid_descriptors_without_paths(transport):
    request, _, _ = preview_fixture(transport)
    from dataclasses import replace

    with pytest.raises(RuntimeUnavailableError):
        transport.request(
            replace(request, files=(ApprovedFile("/secret", "bad", 1, 1),))
        )
    with pytest.raises(RuntimeUnavailableError):
        transport.request(replace(request, size=True))
    with pytest.raises(RuntimeUnavailableError):
        transport.request(
            QueryRead(
                "SELECT 42",
                ((request.dataset, request.files), (request.dataset, request.files)),
            )
        )


def test_v1_transport_rejects_facility_selection_until_paired_worker_support(transport):
    """The old wire must never silently discard a new internal selection."""
    from dataclasses import replace

    request = PreviewRead(
        PUBLIC_DATASETS[1],
        (ApprovedFile("/not-sent", "a" * 64, 1, 1),),
        None,
        None,
        None,
        100,
        facility="001",
    )
    assert b'"operation":"preview"' in transport.request(
        replace(request, facility=None)
    )
    with pytest.raises(RuntimeUnavailableError):
        transport.request(request)
