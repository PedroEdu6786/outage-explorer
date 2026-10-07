"""Execution/fetch faults are classified without exposing engine diagnostics."""

from types import SimpleNamespace
from unittest.mock import Mock

import duckdb
import pytest

from outage_explorer.application.errors import AnalyticalResourceError
from outage_explorer.application.ports.execution import QueryRead
from outage_explorer.application.ports.sql_inspection import SqlRejected
from outage_explorer.infrastructure.duckdb import queries
from tests.integration.test_catalog_preview import ENCODING, EXECUTION


@pytest.fixture
def connection(monkeypatch):
    value = Mock()
    value.execute.return_value = value
    value.description = [("answer", SimpleNamespace(id="integer"))]
    monkeypatch.setattr(queries, "open_restricted", Mock(return_value=value))
    return value


@pytest.mark.parametrize("stage", ["execute", "fetchone"])
@pytest.mark.parametrize(
    "engine_error",
    [
        duckdb.BinderException,
        duckdb.CatalogException,
        duckdb.ConversionException,
        duckdb.InvalidInputException,
        duckdb.InvalidTypeException,
        duckdb.OutOfRangeException,
        duckdb.ParserException,
        duckdb.SyntaxException,
        duckdb.TypeMismatchException,
    ],
)
def test_user_sql_errors_are_safe_and_close_connection(connection, engine_error, stage):
    getattr(connection, stage).side_effect = engine_error("private SQL and paths")
    with pytest.raises(SqlRejected) as rejected:
        queries.execute_query(QueryRead("SELECT 42", ()), EXECUTION, ENCODING)
    assert rejected.value.code == "invalid_sql"
    assert "private" not in str(rejected.value)
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("stage", ["execute", "fetchone"])
def test_engine_memory_exhaustion_is_a_resource_error(connection, stage):
    getattr(connection, stage).side_effect = duckdb.OutOfMemoryException("private")
    with pytest.raises(AnalyticalResourceError) as exhausted:
        queries.execute_query(QueryRead("SELECT 42", ()), EXECUTION, ENCODING)
    assert "private" not in str(exhausted.value)
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("stage", ["execute", "fetchone"])
@pytest.mark.parametrize(
    "engine_error",
    [
        duckdb.IOException,
        duckdb.InternalException,
        duckdb.ConnectionException,
        RuntimeError,
    ],
)
def test_unexpected_engine_failures_are_not_mislabeled_as_user_sql(
    connection, engine_error, stage
):
    failure = engine_error("private")
    getattr(connection, stage).side_effect = failure
    with pytest.raises(engine_error) as raised:
        queries.execute_query(QueryRead("SELECT 42", ()), EXECUTION, ENCODING)
    assert raised.value is failure
    connection.close.assert_called_once_with()


def test_internal_view_setup_failure_is_not_mislabeled_as_user_sql(monkeypatch):
    failure = duckdb.BinderException("private internal view")
    monkeypatch.setattr(queries, "open_restricted", Mock(side_effect=failure))
    with pytest.raises(duckdb.BinderException) as raised:
        queries.execute_query(QueryRead("SELECT 42", ()), EXECUTION, ENCODING)
    assert raised.value is failure
