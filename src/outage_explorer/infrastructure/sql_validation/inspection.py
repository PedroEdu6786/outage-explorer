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
            statements = sqlglot.parse(sql, read="duckdb")
            if len(statements) != 1 or not isinstance(
                statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)
            ):
                raise SqlRejected()
            tree = normalize_identifiers(statements[0], dialect="duckdb")
            nodes = list(tree.walk())
            if len(nodes) > self._max_nodes or any(
                n.depth > self._max_depth for n in nodes
            ):
                raise SqlRejected("invalid_sql")
            for node in nodes:
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
                # SQLGlot also classifies boolean operators as function nodes.
                if isinstance(node, exp.Func) and not isinstance(node, (exp.And, exp.Or)):
                    name = (
                        node.name.upper()
                        if isinstance(node, exp.Anonymous)
                        else node.sql_name()
                    )
                    if (
                        name in _HAZARDOUS_FUNCTIONS
                        or name.startswith("__")
                        or name not in SAFE_FUNCTIONS | {"EXISTS"}
                    ):
                        raise SqlRejected()
                # Qualified functions and object paths are not approved names.
                if isinstance(node, exp.Dot) and isinstance(node.expression, exp.Func):
                    raise SqlRejected()
            grains: set[Grain] = set()
            relations = {dataset.id: dataset.grain for dataset in PUBLIC_DATASETS}
            resolved_tables: set[int] = set()
            for scope in traverse_scope(tree):
                for table in scope.tables:
                    resolved_tables.add(id(table))
                    if (
                        table.catalog
                        or table.db
                        or not isinstance(table.this, exp.Identifier)
                    ):
                        raise SqlRejected()
                    source = scope.sources.get(table.alias_or_name)
                    if isinstance(source, Scope):
                        continue
                    grain = relations.get(table.name.lower())
                    if grain is None:
                        raise SqlRejected()
                    grains.add(grain)
            if any(
                id(table) not in resolved_tables for table in tree.find_all(exp.Table)
            ):
                raise SqlRejected()
            return InspectedSql(sql, frozenset(grains), not grains)
        except SqlRejected:
            raise
        except (
            SqlglotError,
            RecursionError,
            ValueError,
            TypeError,
            UnicodeError,
        ) as exc:
            raise SqlRejected("invalid_sql") from exc
