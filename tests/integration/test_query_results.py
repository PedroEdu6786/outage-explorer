"""Real DuckDB in controlled subprocesses, immutable spools and PostgreSQL access."""

import pickle
import subprocess
import sys
from pathlib import Path

import pytest

from outage_explorer.application.errors import AnalyticalResourceError, QueryPageError
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.application.services.queries import QueryService
from outage_explorer.domain.access import Role
from outage_explorer.infrastructure.query_results.encoding import retain_result
from outage_explorer.infrastructure.query_results.store import (
    BoundedQueryResults,
    ResultBounds,
)
from outage_explorer.infrastructure.sql_validation.inspection import DuckdbSqlInspector
from outage_explorer.infrastructure.worker_runtime.launcher import VerifiedLauncher
from tests.integration import test_catalog_preview as previews
from tests.integration.test_catalog_preview import (
    ENCODING,
    EXECUTION,
    Clock,
    ControlledRuntime,
)

database = previews.database
system = previews.system
browsing = previews.browsing

BOUNDS = ResultBounds(3, 10, 12 * 1024**2, 128 * 1024)


class QueryRuntime(ControlledRuntime):
    def query(self, request, bounds, deadline):
        self.calls.append(request)
        result = subprocess.run(
            [sys.executable, "tests/fixtures/data_api/query_worker.py"],
            input=pickle.dumps((request, bounds, ENCODING)),
            capture_output=True,
            timeout=10,
            env={"PYTHONPATH": str(Path("src").resolve())},
        )
        assert result.returncode == 0, result.stderr.decode()
        output = pickle.loads(result.stdout)
        if isinstance(output, Exception):
            raise output
        return output


@pytest.fixture
def queries(system, browsing, tmp_path):
    preview, cache, _, clock, _, _, _ = browsing
    store = BoundedQueryResults(tmp_path / "results", clock, BOUNDS)
    store.start()
    runtime = QueryRuntime()
    launcher = VerifiedLauncher(
        EXECUTION, runtime, evidence="synthetic controlled tests only"
    )
    service = QueryService(
        system[1]._access,
        DuckdbSqlInspector(max_sql_bytes=65536, max_nodes=10000, max_depth=64),
        system[0],
        cache,
        launcher,
        store,
    )
    yield service, store, clock, runtime, launcher
    store.close()


def test_one_execution_duplicates_direct_and_revisited_pages(queries, system):
    service, _, _, runtime, _ = queries
    token = system[2][Role.ANALYST]
    sql = "SELECT generator AS x, generator AS x FROM generators UNION ALL SELECT generator, generator FROM generators ORDER BY x DESC LIMIT 901"
    first = service.execute(token, sql, page=3, page_size=100)
    assert [col["name"] for col in first["columns"]] == ["x", "x"]
    pages = [service.page(token, first["query_id"], page=n) for n in range(1, 11)]
    assert sum(len(page["rows"]) for page in pages) == 901
    assert service.page(token, first["query_id"], page=3) == first
    rows = [row for page in pages for row in page["rows"]]
    assert rows == sorted(rows, reverse=True)
    assert len({tuple(row) for row in rows}) < len(rows)
    assert runtime.calls[0].sql == sql and len(runtime.calls) == 1
    assert runtime.reaps == 1


@pytest.mark.parametrize("count,reason", [(0, None), (1000, None), (1001, "row_limit")])
def test_exact_and_over_row_limit_reference_free(queries, system, count, reason):
    service, _, _, runtime, _ = queries
    output = service.execute(
        system[2][Role.VIEWER],
        (
            "SELECT x FROM (VALUES "
            + ",".join(f"({i})" for i in range(max(1, count)))
            + ") a(x)"
            + (" WHERE false" if count == 0 else "")
        ),
        page_size=500,
    )
    assert output["retained_row_count"] == min(count, 1000)
    assert output["truncation_reason"] == reason
    assert output["rows"] == [[str(i)] for i in range(min(count, 500))]
    assert runtime.calls[0].relations == ()


def test_initial_out_of_range_keeps_owned_result(queries, system):
    service, _, _, runtime, _ = queries
    token = system[2][Role.VIEWER]
    with pytest.raises(QueryPageError) as caught:
        service.execute(token, "SELECT 42 AS x", page=2)
    identity = caught.value.identity
    assert identity is not None and identity.owner == system[3][Role.VIEWER].id
    assert service.page(token, identity.id)["rows"] == [["42"]]
    assert len(runtime.calls) == 1
    with pytest.raises(QueryPageError, match="Invalid retained"):
        service.page(token, identity.id, page_size=500)


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT [1,2,NULL] AS x, {'é':'😀'} AS x", [["1", "2", None], ["😀"]]),
        ("SELECT NULL AS x, 1.250::DECIMAL(5,3) AS d", [None, "1.250"]),
        ("SELECT map(['é'],[42]) AS m", [[["é", "42"]]]),
    ],
)
def test_nested_utf8_and_null_lossless(queries, system, sql, expected):
    output = queries[0].execute(system[2][Role.VIEWER], sql)
    assert output["rows"] == [expected]


def test_utf8_whole_document_prefix_never_skips(queries, system):
    service, store, _, runtime, _ = queries
    sql = "SELECT CAST(list_resize(['😀'],60000,'😀') AS VARCHAR) AS x FROM (VALUES(0),(1),(2),(3)) a(x)"
    page = service.execute(system[2][Role.VIEWER], sql, page_size=1)
    assert page["retained_row_count"] == 2 and page["truncation_reason"] == "byte_limit"
    second = service.page(system[2][Role.VIEWER], page["query_id"], page=2)
    assert second["rows"] == page["rows"]
    document = next(store._directory.glob("*.json")).read_bytes()
    assert len(document) <= 1048576
    assert len(runtime.calls) == 1


@pytest.mark.parametrize(
    "sql,count",
    [
        (
            "SELECT CAST(list_resize(['a'],220000,'a') AS VARCHAR) AS a,CAST(list_resize(['b'],220000,'b') AS VARCHAR) AS b",
            0,
        ),
        (
            "SELECT CASE WHEN x=0 THEN 'small' ELSE CAST(list_resize(['a'],220000,'a') AS VARCHAR) END AS a,CAST(list_resize(['b'],220000,'b') AS VARCHAR) AS b FROM (VALUES(0),(1),(2)) a(x)",
            1,
        ),
    ],
)
def test_oversized_first_and_later_rows(queries, system, sql, count):
    output = queries[0].execute(system[2][Role.VIEWER], sql)
    assert output["retained_row_count"] == count
    assert output["truncation_reason"] == "byte_limit"


def test_schema_overhead_and_output_size_mismatch(tmp_path):
    from outage_explorer.domain.datasets import Column, ValueType
    from outage_explorer.infrastructure.query_results.encoding import EncodingLimit

    column = Column("x" * 70000, ValueType("string"))
    with pytest.raises(EncodingLimit):
        retain_result((column,), [], ENCODING)
    store = BoundedQueryResults(tmp_path / "spool", Clock(), BOUNDS)
    store.start()
    reservation = store.reserve("user")
    encoded = retain_result((Column("x", ValueType("integer")),), [(1,)], ENCODING)
    invalid = [
        QueryOutput(encoded.document, 2, None),
        QueryOutput(b" " + encoded.document, 1, None),
        QueryOutput(b"x" * 1048577, 0, None),
    ]
    for output in invalid:
        with pytest.raises(AnalyticalResourceError):
            reservation.complete(output, frozenset(), None, 100)
    reservation.close()
    store.close()


@pytest.mark.parametrize(
    "sql",
    [
        "WITH a AS (SELECT generator FROM generators) SELECT count(*) AS n FROM a",
        "SELECT generator, row_number() OVER (ORDER BY generator) AS n FROM generators ORDER BY generator LIMIT 3",
        "SELECT count(*) AS n FROM facilities JOIN generators USING(facility)",
        "SELECT count(*) AS n FROM (SELECT * FROM national) a",
    ],
)
def test_analytical_semantics_and_unchanged_sql(queries, system, sql):
    output = queries[0].execute(system[2][Role.ANALYST], sql)
    assert output["rows"]
    assert queries[3].calls[0].sql == sql


def test_oversized_single_cell_is_explicit_byte_truncation(queries, system):
    output = queries[0].execute(
        system[2][Role.VIEWER],
        "SELECT CAST(list_resize(['a'],450000,'a') AS VARCHAR) AS x",
    )
    assert output["rows"] == []
    assert output["retained_row_count"] == 0
    assert output["truncation_reason"] == "byte_limit"
    assert output["total_pages"] == 1


def test_encoding_exact_reserved_utf8_boundary():
    import json

    from outage_explorer.domain.datasets import Column, ValueType
    from outage_explorer.infrastructure.query_results.encoding import canonical_json

    columns = (Column("é", ValueType("string")),)
    empty = retain_result(columns, [], ENCODING)
    metadata = json.loads(empty.document)
    metadata.update(
        retained_row_count=1000, truncated=True, truncation_reason="byte_limit"
    )
    reserved = len(canonical_json(metadata)) + 1
    fitting = 1048576 - reserved - 4
    exact = retain_result(columns, [("a" * fitting,)], ENCODING)
    over = retain_result(columns, [("a" * (fitting + 1),)], ENCODING)
    assert exact.retained_row_count == 1 and exact.truncation_reason is None
    assert len(exact.document) <= 1048576
    assert over.retained_row_count == 0 and over.truncation_reason == "byte_limit"
