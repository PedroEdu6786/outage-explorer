import io
import json
from datetime import date
from decimal import Decimal

import pytest

from outage_explorer.application.ports.execution import PreviewRows
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.entrypoints.query_worker import run
from outage_explorer.infrastructure.query_results.encoding import EncodingBounds
from outage_explorer.infrastructure.query_results.preview_encoding import (
    PreviewEncoding,
)
from outage_explorer.infrastructure.sql_validation.inspection import DuckdbSqlInspector
from outage_explorer.infrastructure.worker_runtime.protocol import (
    MAX_REQUEST_BYTES,
    AnalyticalWorker,
)


@pytest.fixture
def worker(tmp_path):
    calls = []

    def preview(request):
        calls.append(request)
        return PreviewRows(
            (
                (
                    date(2026, 9, 1),
                    Decimal("100"),
                    Decimal("10"),
                    Decimal("10"),
                    Decimal("10"),
                    "1",
                    "10",
                    "10.00",
                    "10.00",
                ),
            ),
            (("2026-09-01",),),
            False,
        )

    def query(request):
        calls.append(request)
        return QueryOutput(b'{"rows":[["42"]]}', 1, None)

    return AnalyticalWorker(
        tmp_path,
        preview,
        query,
        DuckdbSqlInspector(max_sql_bytes=65536, max_nodes=10000, max_depth=64),
        PreviewEncoding(EncodingBounds(1048576, 16, 10000, 100, 65536)),
    ), calls


def request(**changes):
    return {
        "version": 1,
        "operation": "query",
        "sql": "SELECT 42",
        "relations": [],
        **changes,
    }


def test_query_is_unchanged_and_reference_free(worker):
    adapter, calls = worker
    sql = "SELECT 42 AS answer ORDER BY answer"
    response = json.loads(adapter.execute(json.dumps(request(sql=sql)).encode()))
    assert response["result"]["rows"] == [["42"]]
    assert calls[0].sql == sql
    assert calls[0].relations == ()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"version":1,"version":1,"operation":"query","sql":"SELECT 42","relations":[]}',
        b'{"version":NaN}',
        b"[]",
        b"{",
        b"x" * (MAX_REQUEST_BYTES + 1),
    ],
)
def test_invalid_transport_never_executes(worker, raw):
    adapter, calls = worker
    response = json.loads(adapter.execute(raw))
    assert response["error"]["code"] == "invalid_request"
    assert calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"version": True},
        {"version": 2},
        {"extra": 1},
        {"sql": "SELECT * FROM national"},
        {
            "relations": [
                {
                    "dataset": "national",
                    "files": [{"sha256": "../secret", "byte_count": 1, "rows": 1}],
                }
            ]
        },
    ],
)
def test_rejected_request_never_executes(worker, changes):
    adapter, calls = worker
    assert (
        json.loads(adapter.execute(json.dumps(request(**changes)).encode()))["error"][
            "code"
        ]
        == "invalid_request"
    )
    assert calls == []


def test_external_sql_is_rejected(worker):
    adapter, calls = worker
    response = adapter.execute(
        json.dumps(request(sql="SELECT * FROM read_csv('/secret')")).encode()
    )
    assert json.loads(response)["error"]["code"] == "unsupported_sql"
    assert b"/secret" not in response
    assert calls == []


def test_preview_uses_trusted_input_root_and_lossless_values(worker, tmp_path):
    adapter, calls = worker
    payload = {
        "version": 1,
        "operation": "preview",
        "dataset": "national",
        "files": [{"sha256": "a" * 64, "byte_count": 100, "rows": 1}],
        "start_date": None,
        "end_date": None,
        "after": None,
        "page_size": 100,
    }
    response = json.loads(adapter.execute(json.dumps(payload).encode()))
    assert calls[0].files[0].path == str(tmp_path / ("a" * 64 + ".parquet"))
    assert response["result"]["rows"][0][0] == "2026-09-01"
    assert response["result"]["rows"][0][1] == "100"
    assert response["result"]["keys"] == [["2026-09-01"]]


def test_engine_errors_are_sanitized(worker):
    adapter, _ = worker

    def broken(request):
        raise RuntimeError("secret provider path and SQL")

    adapter._query = broken
    response = adapter.execute(json.dumps(request()).encode())
    assert json.loads(response)["error"]["code"] == "worker_execution_failed"
    assert b"secret" not in response


def test_stdio_reads_a_bounded_request_and_exits(worker):
    adapter, calls = worker
    sink = io.BytesIO()
    assert run(adapter.execute, io.BytesIO(b"x" * (MAX_REQUEST_BYTES + 100)), sink) == 1
    assert json.loads(sink.getvalue())["error"]["code"] == "invalid_request"
    assert calls == []
