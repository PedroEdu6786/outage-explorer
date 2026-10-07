"""Pure descriptor publication contracts, independent of cutover/storage."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.publication import (
    DatasetSummary,
    PublishedGeneration,
    ResourcePublishedGeneration,
)


@pytest.fixture
def generation():
    names = ("national", "facilities", "generators")
    return ResourcePublishedGeneration(
        "generation-2",
        "run-2",
        "generation-1",
        "v1",
        datetime(2026, 10, 6, tzinfo=UTC),
        tuple(
            DatasetSummary(
                grain,
                "v1",
                10,
                date(2026, 4, 2),
                date(2026, 10, 1),
                f"configured/generations/generation-2/{name}.parquet",
                "a" * 64,
                1234,
            )
            for grain, name in zip(AnalyticalGrain, names, strict=True)
        ),
    )


def test_resource_contract_retains_exact_identity_without_manifest(generation):
    generation.validate()
    assert not hasattr(generation, "manifest_key")
    assert not hasattr(generation, "manifest_digest")
    assert generation.base_generation_id == "generation-1"
    assert generation.datasets[1].object_key.endswith("facilities.parquet")
    assert generation.datasets[2].sha256 == "a" * 64
    assert generation.datasets[2].byte_count == 1234


@pytest.mark.parametrize(
    "changes",
    [
        {"object_key": None},
        {"sha256": None},
        {"byte_count": None},
        {"object_key": ""},
        {"object_key": "/absolute/file.parquet"},
        {"object_key": "bad/../file.parquet"},
        {"object_key": "a//file.parquet"},
        {"object_key": "bad\\file.parquet"},
        {"object_key": "a?b.parquet"},
        {"object_key": "x" * 1025},
        {"sha256": "A" * 64},
        {"sha256": "a" * 63},
        {"sha256": "z" * 64},
        {"byte_count": 0},
        {"byte_count": -1},
        {"byte_count": True},
        {"rows": 0},
        {"rows": True},
        {"schema_version": "unknown"},
        {"start": date(2027, 1, 1)},
        {"object_key": "configured/generations/other/national.parquet"},
        {"object_key": "configured/generations/generation-2/facilities.parquet"},
    ],
)
def test_resource_descriptor_rejects_missing_unsafe_or_inconsistent_fields(
    generation, changes
):
    invalid = replace(
        generation,
        datasets=(replace(generation.datasets[0], **changes), *generation.datasets[1:]),
    )
    with pytest.raises(ValueError):
        invalid.validate()


@pytest.mark.parametrize(
    "changes",
    [
        {"id": ""},
        {"run_id": ""},
        {"base_generation_id": ""},
        {"base_generation_id": "generation-2"},
        {"verification_version": "unknown"},
        {"verified_at": datetime(2026, 10, 6)},
        {"datasets": ()},
    ],
)
def test_resource_generation_rejects_invalid_admitted_identity(generation, changes):
    with pytest.raises(ValueError):
        replace(generation, **changes).validate()


def test_one_distinct_descriptor_per_grain_required(generation):
    with pytest.raises(ValueError):
        replace(
            generation,
            datasets=(
                generation.datasets[0],
                generation.datasets[0],
                generation.datasets[2],
            ),
        ).validate()


def test_legacy_contract_remains_separate_and_resource_requires_descriptors(generation):
    summaries = tuple(
        replace(item, object_key=None, sha256=None, byte_count=None)
        for item in generation.datasets
    )
    legacy = PublishedGeneration(
        "legacy",
        "run",
        None,
        "manifest",
        "a" * 64,
        "v1",
        generation.verified_at,
        summaries,
    )
    legacy.validate()
    with pytest.raises(ValueError):
        replace(generation, datasets=summaries).validate()


def test_partial_descriptor_rejected_even_on_staged_legacy_contract(generation):
    partial = DatasetSummary(
        AnalyticalGrain.NATIONAL,
        "v1",
        1,
        date(2026, 1, 1),
        date(2026, 1, 1),
        object_key="some/file",
    )
    with pytest.raises(ValueError):
        partial.validate()


def test_legacy_manifest_and_resource_descriptors_cannot_mix(generation):
    with pytest.raises(ValueError):
        PublishedGeneration(
            "legacy",
            "run",
            None,
            "manifest",
            "a" * 64,
            "v1",
            generation.verified_at,
            generation.datasets,
        ).validate()
