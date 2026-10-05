import pytest

from outage_explorer.application.ports.sql_inspection import SqlRejected
from outage_explorer.infrastructure.sql_validation.inspection import DuckdbSqlInspector


@pytest.fixture
def inspector():
    return DuckdbSqlInspector(max_sql_bytes=65536, max_nodes=10000, max_depth=100)


@pytest.mark.parametrize(
    ("sql", "grains"),
    [
        ("SELECT * FROM national", {"national"}),
        (
            "WITH MixedCase AS (SELECT * FROM generators) SELECT * FROM MIXEDCASE",
            {"generator"},
        ),
        (
            "WITH national AS (SELECT * FROM generators) SELECT * FROM national",
            {"generator"},
        ),
        (
            "WITH unused AS (SELECT * FROM generators) SELECT * FROM national",
            {"national", "generator"},
        ),
        (
            "SELECT (SELECT MAX(capacity_mw) FROM generators) FROM national",
            {"national", "generator"},
        ),
        (
            "SELECT * FROM NATIONAL n JOIN facilities f USING(period)",
            {"national", "facility"},
        ),
        (
            "SELECT * FROM national WHERE EXISTS(SELECT 1 FROM generators)",
            {"national", "generator"},
        ),
        (
            "WITH RECURSIVE n(x) AS (SELECT capacity_mw FROM national UNION ALL SELECT x-1 FROM n WHERE x>0) SELECT * FROM n",
            {"national"},
        ),
        ("SELECT sin(0), ln(1), random()", set()),
        ("SELECT 1 /* FROM generators */", set()),
    ],
)
def test_complete_scoped_references_and_original_sql(inspector, sql, grains):
    result = inspector.inspect(sql)
    assert result.sql == sql
    assert result.grains == grains
    assert result.reference_free is (not grains)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "-- only comment",
        "SELECT",
        "SELECT 1; SELECT 2",
        "DELETE FROM national",
        "INSERT INTO national SELECT * FROM facilities",
        "COPY national TO '/tmp/x'",
        "ATTACH '/tmp/x.db'",
        "SET threads=99",
        "PRAGMA database_list",
        "INSTALL httpfs",
        "SELECT * FROM read_parquet('/tmp/private.parquet')",
        "SELECT * FROM '/tmp/private.parquet'",
        "SELECT * FROM read_csv('https://example.com/private')",
        "SELECT * FROM sqlite_scan('/tmp/x','users')",
        "SELECT * FROM query('SELECT * FROM generators')",
        "SELECT * FROM query_table('generators')",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM pg_catalog.pg_tables",
        "SELECT * FROM duckdb_tables()",
        "SELECT * FROM main.national",
        "SELECT getenv('AWS_SECRET_ACCESS_KEY')",
        "SELECT current_setting('secret_directory')",
        "SELECT getvariable('secret')",
        "SELECT nextval('x')",
        "SELECT write_log('private')",
        "SELECT main.sin(1)",
        "SELECT mystery_function(1)",
        "SELECT * FROM unknown_relation",
        "WITH n AS (SELECT * FROM generators) SELECT * FROM read_blob('/tmp/x')",
        "SELECT * INTO other FROM national",
        "SELECT $1",
        "SELECT ?",
        "SELECT json_serialize_plan('SELECT * FROM generators')",
        "SELECT in_search_path('main','secret')",
        "SELECT '\ud800'",
    ],
)
def test_hazardous_or_unresolved_constructs_fail_with_safe_error(inspector, sql):
    with pytest.raises(SqlRejected) as failure:
        inspector.inspect(sql)
    assert str(failure.value) in ("SQL is not supported", "Invalid SQL")
    assert "/tmp" not in str(failure.value)


def test_explicit_parser_bounds():
    with pytest.raises(ValueError):
        DuckdbSqlInspector(max_sql_bytes=0, max_nodes=1, max_depth=1)
    for kwargs, sql in [
        ({"max_sql_bytes": 3}, "SELECT 1"),
        ({"max_nodes": 2}, "SELECT 1+2"),
        ({"max_depth": 2}, "SELECT 1+(2+(3+4))"),
    ]:
        settings = {
            "max_sql_bytes": 65536,
            "max_nodes": 10000,
            "max_depth": 100,
        } | kwargs
        with pytest.raises(SqlRejected):
            DuckdbSqlInspector(**settings).inspect(sql)
