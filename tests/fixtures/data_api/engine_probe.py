"""Controlled compatibility subprocess, never a product worker or sandbox."""

import json
from decimal import Decimal

import duckdb

from outage_explorer.domain.datasets import Column
from outage_explorer.infrastructure.query_results.duckdb_types import value_type
from outage_explorer.infrastructure.query_results.encoding import (
    EncodingBounds,
    retain_result,
)
from outage_explorer.infrastructure.sql_validation.inspection import DuckdbSqlInspector

BOUNDS = EncodingBounds(1_048_576, 16, 10000, 100, 65536)
INSPECTOR = DuckdbSqlInspector(max_sql_bytes=65536, max_nodes=10000, max_depth=100)


def main():
    db = duckdb.connect(
        config={
            "enable_external_access": False,
            "autoload_known_extensions": False,
            "autoinstall_known_extensions": False,
            "threads": 1,
            "memory_limit": "128MB",
        }
    )
    for name in ("national", "facilities", "generators"):
        db.execute(
            f"CREATE TABLE {name}(period DATE, capacity_mw DECIMAL(38,12), facility VARCHAR)"
        )
        db.execute(
            f"INSERT INTO {name} VALUES ('2026-10-01', 1000, '00001'), ('2026-09-30', 2000, '00002')"
        )
    corpus = [
        ("SELECT sum(capacity_mw) FROM national", {"national"}, [(Decimal("3000"),)]),
        (
            "SELECT n.period FROM national n JOIN facilities f USING(period) WHERE f.facility='00001'",
            {"national", "facility"},
            None,
        ),
        (
            "WITH national AS (SELECT * FROM generators) SELECT count(*) FROM national",
            {"generator"},
            [(2,)],
        ),
        (
            "SELECT count(*) FROM facilities WHERE period IN (SELECT period FROM national)",
            {"facility", "national"},
            [(2,)],
        ),
        (
            "SELECT row_number() OVER (ORDER BY period), facility FROM generators ORDER BY period",
            {"generator"},
            [(1, "00002"), (2, "00001")],
        ),
        (
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<3) SELECT * FROM n",
            set(),
            [(1,), (2,), (3,)],
        ),
        (
            "SELECT period FROM national UNION SELECT period FROM facilities",
            {"national", "facility"},
            None,
        ),
        (
            "SELECT period FROM national INTERSECT SELECT period FROM facilities",
            {"national", "facility"},
            None,
        ),
        (
            "SELECT period FROM national EXCEPT SELECT period FROM facilities",
            {"national", "facility"},
            [],
        ),
        ("SELECT sin(0), log10(100), sqrt(4), abs(-2)", set(), [(0.0, 2.0, 2.0, 2)]),
        (
            "SELECT capacity_mw FROM national ORDER BY period LIMIT 1 OFFSET 1",
            {"national"},
            [(Decimal("1000"),)],
        ),
    ]
    for sql, grains, expected in corpus:
        inspected = INSPECTOR.inspect(sql)
        assert inspected.sql == sql and inspected.grains == grains
        result = db.execute(inspected.sql).fetchall()
        if expected is not None:
            assert result == expected, (sql, result)
    sql = """SELECT 9007199254740993::HUGEINT AS x,
        0.123456789012::DECIMAL(38,12) AS x, 'NaN'::DOUBLE AS nan,
        'Infinity'::DOUBLE AS positive_infinity, '-Infinity'::DOUBLE AS negative_infinity,
        1.25::DOUBLE AS finite, TRUE AS flag, NULL::INTEGER AS missing,
        DATE '2026-10-01' AS day, TIME '12:34:56.123456' AS clock,
        TIMESTAMP '2026-10-01 12:34:56.123456' AS local_time,
        TIMESTAMPTZ '2026-10-01 12:34:56+02:00' AS instant,
        from_hex('00FF') AS bytes, [1, NULL, 9007199254740993] AS values,
        {'label': 'é', 'amount': 1.25::DECIMAL(8,2)} AS record,
        map(['one', 'two'], [1, NULL]) AS mapping"""
    inspected = INSPECTOR.inspect(sql)
    result = db.execute(inspected.sql)
    columns = [
        Column(item[0], value_type(item[1]), nullable=None)
        for item in result.description
    ]
    encoded = retain_result(columns, result.fetchall(), BOUNDS)
    document = json.loads(encoded.document)
    assert document["rows"][0] == [
        "9007199254740993",
        "0.123456789012",
        "NaN",
        "Infinity",
        "-Infinity",
        1.25,
        True,
        None,
        "2026-10-01",
        "12:34:56.123456",
        "2026-10-01T12:34:56.123456",
        "2026-10-01T10:34:56Z",
        "AP8=",
        ["1", None, "9007199254740993"],
        ["é", "1.25"],
        [["one", "1"], ["two", None]],
    ]
    for nested_sql, expected in [
        ("SELECT map([[1,2]], ['a'])", [[[["1", "2"], "a"]]]),
        ("SELECT map([{'x':1}], [[1,NULL]])", [[[["1"], ["1", None]]]]),
    ]:
        result = db.execute(INSPECTOR.inspect(nested_sql).sql)
        nested_columns = [
            Column(item[0], value_type(item[1]), nullable=None)
            for item in result.description
        ]
        actual = json.loads(
            retain_result(nested_columns, result.fetchall(), BOUNDS).document
        )
        assert actual["rows"][0] == expected
    # Synthetic row streams exercise caps with engine values; range is fixture
    # setup, not an advertised user table-function capability.
    result = db.execute("SELECT i FROM range(1001) AS fixture(i)")
    cap_columns = [
        Column(item[0], value_type(item[1]), nullable=None)
        for item in result.description
    ]
    capped = retain_result(cap_columns, iter(lambda: result.fetchone(), None), BOUNDS)
    assert capped.retained_row_count == 1000 and capped.truncation_reason == "row_limit"
    result = db.execute(
        "SELECT repeat('x', 1048100) AS payload UNION ALL SELECT repeat('z', 1000)"
    )
    byte_columns = [
        Column(item[0], value_type(item[1]), nullable=None)
        for item in result.description
    ]
    byte_capped = retain_result(
        byte_columns, iter(lambda: result.fetchone(), None), BOUNDS
    )
    assert (
        byte_capped.retained_row_count == 1
        and byte_capped.truncation_reason == "byte_limit"
    )
    assert len(byte_capped.document) <= 1048576
    print(
        json.dumps(
            {
                "queries_verified": len(corpus) + 5,
                "engine_version": duckdb.__version__,
                "encoded": document,
            },
            ensure_ascii=False,
        )
    )
    db.close()


if __name__ == "__main__":
    main()
