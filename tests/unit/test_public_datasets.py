import pyarrow as pa

from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.infrastructure.parquet.schemas import schema_for


def test_public_schema_is_exact_nonnullable_projection_of_verified_physical_v1():
    expected = {
        "national": "national",
        "facilities": "facility",
        "generators": "generator",
    }
    assert {item.id: item.grain for item in PUBLIC_DATASETS} == expected
    for dataset in PUBLIC_DATASETS:
        physical = schema_for("modeled", dataset.grain)
        assert dataset.schema_version == physical.metadata[b"version"].decode()
        for column in dataset.columns:
            field = physical.field(column.name)
            assert column.nullable is field.nullable is False
            typ = column.value_type
            if typ.kind == "decimal":
                assert field.type == pa.decimal128(typ.precision, typ.scale)
            elif typ.kind == "date":
                assert field.type == pa.date32()
            else:
                assert typ.kind == "string"
                assert field.type == pa.string()
        assert not {"origin", "identity", "capacity_source", "share_numerator"} & {
            column.name for column in dataset.columns
        }
    national = {col.name for col in PUBLIC_DATASETS[0].columns}
    assert {
        "calculated_percentage_rounded",
        "reported_percentage",
        "percentage_numerator",
        "percentage_denominator",
        "calculated_percentage_display",
        "reported_percentage_display",
    } <= national
    assert "facility_name" not in national
