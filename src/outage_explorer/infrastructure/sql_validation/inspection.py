"""Fail-closed DuckDB reference analysis. Never execute or rewrite submitted SQL."""

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.scope import Scope, traverse_scope

from outage_explorer.application.ports.sql_inspection import InspectedSql, SqlRejected
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.observations import Grain
from outage_explorer.infrastructure.sql_validation.functions import SAFE_FUNCTIONS

_HAZARDOUS_FUNCTIONS = frozenset(
    {
        "JSON_SERIALIZE_PLAN",
        "JSON_SERIALIZE_SQL",
        "JSON_DESERIALIZE_SQL",
        "IN_SEARCH_PATH",
    }
)
_READ_QUERY_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except)


def _parse_read_query(sql: str) -> exp.Expression:
    statements = sqlglot.parse(sql, read="duckdb")
    if len(statements) != 1:
        raise SqlRejected()

    statement = statements[0]
    if not isinstance(statement, _READ_QUERY_TYPES):
        raise SqlRejected()

    return normalize_identifiers(statement, dialect="duckdb")


def _validate_function(node: exp.Func) -> None:
    # SQLGlot also classifies boolean operators as function nodes.
    if isinstance(node, (exp.And, exp.Or)):
        return
    name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name()
    if (
        name in _HAZARDOUS_FUNCTIONS
        or name.startswith("__")
        or name not in SAFE_FUNCTIONS | {"EXISTS"}
    ):
        raise SqlRejected()


def _validate_node(node: exp.Expr) -> None:
    if isinstance(node, exp.Select) and not node.expressions:
        raise SqlRejected("invalid_sql")
    if isinstance(
        node,
        (
            exp.DDL,
            exp.DML,
            exp.Command,
            exp.Into,
            exp.Placeholder,
            exp.Parameter,
        ),
    ):
        raise SqlRejected()
    if isinstance(node, exp.Func):
        _validate_function(node)
    # Qualified functions and object paths are not approved names.
    if isinstance(node, exp.Dot) and isinstance(node.expression, exp.Func):
        raise SqlRejected()


def _validate_tree(tree: exp.Expression, max_nodes: int, max_depth: int) -> None:
    nodes = list(tree.walk())
    if len(nodes) > max_nodes or any(node.depth > max_depth for node in nodes):
        raise SqlRejected("invalid_sql")
    for node in nodes:
        _validate_node(node)


def _public_grain(
    scope: Scope, table: exp.Table, dataset_grains: dict[str, Grain]
) -> Grain | None:
    if table.catalog or table.db or not isinstance(table.this, exp.Identifier):
        raise SqlRejected()
    if isinstance(scope.sources.get(table.alias_or_name), Scope):
        return None  # A CTE or subquery reference, not a public dataset.
    grain = dataset_grains.get(table.name.lower())
    if grain is None:
        raise SqlRejected()
    return grain


def _require_all_tables_scoped(
    tree: exp.Expression, scoped_table_ids: set[int]
) -> None:
    # Reject table nodes that SQLGlot did not account for during scope traversal.
    if any(id(table) not in scoped_table_ids for table in tree.find_all(exp.Table)):
        raise SqlRejected()


def _referenced_grains(tree: exp.Expression) -> frozenset[Grain]:
    dataset_grains = {dataset.id: dataset.grain for dataset in PUBLIC_DATASETS}
    grains: set[Grain] = set()
    scoped_table_ids: set[int] = set()
    for scope in traverse_scope(tree):
        for table in scope.tables:
            scoped_table_ids.add(id(table))
            grain = _public_grain(scope, table, dataset_grains)
            if grain is not None:
                grains.add(grain)
    _require_all_tables_scoped(tree, scoped_table_ids)
    return frozenset(grains)


class DuckdbSqlInspector:
    """Caller provides reviewed parser budgets; no product runtime is enabled here."""

    def __init__(self, *, max_sql_bytes: int, max_nodes: int, max_depth: int) -> None:
        if min(max_sql_bytes, max_nodes, max_depth) <= 0:
            raise ValueError("SQL inspection bounds must be positive")
        self._max_sql_bytes = max_sql_bytes
        self._max_nodes = max_nodes
        self._max_depth = max_depth

    def inspect(self, sql: str) -> InspectedSql:
        try:
            if (
                len(sql) > self._max_sql_bytes
                or len(sql.encode("utf-8")) > self._max_sql_bytes
            ):
                raise SqlRejected("invalid_sql")
            tree = _parse_read_query(sql)
            _validate_tree(tree, self._max_nodes, self._max_depth)
            grains = _referenced_grains(tree)
            return InspectedSql(sql, grains, not grains)
        except SqlRejected:
            raise
        except (
            SqlglotError,
            RecursionError,
            ValueError,
            TypeError,
        ) as exc:
            raise SqlRejected("invalid_sql") from exc
