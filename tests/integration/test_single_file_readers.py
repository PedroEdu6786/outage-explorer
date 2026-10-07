"""Readers pin exact unified resource files and expose restricted public views."""

import json
import pickle
import stat
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import pyarrow.parquet as pq
import pytest

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
)
from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.application.ports.artifacts import ArtifactError
from outage_explorer.application.ports.execution import ExecutionBounds, QueryRead
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.publication import (
    DatasetSummary,
    ResourcePublishedGeneration,
)
from outage_explorer.infrastructure.local_cache import modeled as cache_module
from outage_explorer.infrastructure.local_cache.modeled import VerifiedResourceCache
from tests.integration import test_connector_cli as connector
from tests.integration.test_catalog_preview import CACHE, ENCODING, EXECUTION
from tests.integration.test_connector_cli import ARTIFACT, row

DAYS = ("2026-09-01", "2026-09-02")


@pytest.fixture
def published(tmp_path):
    rows = {
        "national": [row("national", period=day) for day in DAYS],
        "facility": [
            row("facility", period=day, facility=facility)
            for day in DAYS
            for facility in ("001", "002")
        ],
        "generator": [
            row("generator", period=day, facility="001", generator=generator)
            for day in DAYS
            for generator in ("01", "02")
        ],
    }
    result, _ = connector.execute(tmp_path / "connector", rows)
    store, manifest = connector.reopen(tmp_path / "connector", result.report.candidate)
    counts = {item.grain: item.candidate_count for item in manifest.summaries}
    return store, manifest, counts


class Objects:
    def __init__(self, store, manifest, tamper=None):
        self.store, self.manifest, self.tamper = store, manifest, tamper or {}

    def read(self, reference):
        change = self.tamper.get(reference.key)
        if change == "missing":
            raise ArtifactError("Object unavailable")
        local = replace(reference, key=reference.sha256)
        for chunk in self.store.read(local):
            yield chunk if change is None else b"X" * len(chunk)


def generation(manifest, counts, **changes):
    summaries = {item.grain: item for item in manifest.summaries}
    return ResourcePublishedGeneration(
        manifest.generation_id,
        "synthetic-run",
        None,
        "v1",
        datetime.now(UTC),
        tuple(
            DatasetSummary(
                grain,
                "v1",
                counts[grain.value],
                summaries[grain.value].first_period,
                summaries[grain.value].last_period,
                f"connector/generations/{manifest.generation_id}/{name}.parquet",
                next(
                    ref.object.sha256
                    for ref in manifest.resources
                    if ref.grain == grain.value
                ),
                next(
                    ref.object.byte_count
                    for ref in manifest.resources
                    if ref.grain == grain.value
                ),
            )
            for grain, name in zip(
                AnalyticalGrain, ("national", "facilities", "generators"), strict=True
            )
        ),
    )


def cache(tmp_path, published, tamper=None, bounds=CACHE):
    store, manifest, _ = published
    return VerifiedResourceCache(
        tmp_path / "cache", Objects(store, manifest, tamper), ARTIFACT, bounds
    )


def test_cache_pins_exact_resource_file_without_rewriting(tmp_path, published):
    _, manifest, counts = published
    reader = cache(tmp_path, published)
    published_generation = generation(manifest, counts)
    with (
        patch.object(pq, "write_table", side_effect=AssertionError("write")),
        patch.object(pq, "ParquetWriter", side_effect=AssertionError("write")),
    ):
        pins = {
            dataset.id: reader.prepare(published_generation, dataset)
            for dataset in PUBLIC_DATASETS
        }
    for dataset in PUBLIC_DATASETS:
        (file,) = pins[dataset.id].files
        ref = next(r for r in manifest.resources if r.grain == dataset.grain)
        assert (file.sha256, file.byte_count, file.rows) == (
            ref.object.sha256,
            ref.object.byte_count,
            ref.row_count,
        )
        assert file.rows == counts[dataset.grain]
        path = Path(file.path)
        assert path.name == f"{ref.object.sha256}-{dataset.id}.parquet"
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
        assert set(c.name for c in dataset.columns) < set(pq.read_schema(path).names)
    assert "modeled_from_record" not in Path(cache_module.__file__).read_text()
    assert len(list((tmp_path / "cache").glob("*.parquet"))) == 3
    for pin in pins.values():
        pin.close()


@pytest.mark.parametrize("fault", ["corrupt", "missing"])
def test_unverifiable_resource_file_is_unavailable_without_fallback(
    tmp_path, published, fault
):
    _, manifest, counts = published
    reader = cache(
        tmp_path,
        published,
        {f"connector/generations/{manifest.generation_id}/facilities.parquet": fault},
    )
    dataset = next(d for d in PUBLIC_DATASETS if d.grain == "facility")
    with pytest.raises(DataUnavailableError):
        reader.prepare(generation(manifest, counts), dataset)
    assert not list((tmp_path / "cache").glob("*.parquet"))
    assert not reader._entries


def test_publication_summary_must_match_exact_resource_files_and_coverage(
    tmp_path, published
):
    _, manifest, counts = published
    reader = cache(tmp_path, published)
    published_generation = generation(manifest, counts)
    first = published_generation.datasets[0]
    wrong_coverage = replace(
        published_generation,
        datasets=(
            replace(first, end=date(2026, 9, 3)),
            *published_generation.datasets[1:],
        ),
    )
    with pytest.raises(DataUnavailableError):
        reader.prepare(wrong_coverage, PUBLIC_DATASETS[0])
    wrong_rows = replace(
        published_generation,
        datasets=(
            replace(first, rows=first.rows + 1),
            *published_generation.datasets[1:],
        ),
    )
    with pytest.raises(DataUnavailableError):
        reader.prepare(wrong_rows, PUBLIC_DATASETS[0])
    assert not list((tmp_path / "cache").glob("*.parquet"))


def test_pinned_file_survives_a_full_cache_and_is_evicted_after_release(
    tmp_path, published
):
    _, manifest, counts = published
    reader = cache(tmp_path, published, bounds=replace(CACHE, files=1))
    published_generation = generation(manifest, counts)
    pin = reader.prepare(published_generation, PUBLIC_DATASETS[0])
    with pytest.raises(AnalyticalResourceError):
        reader.prepare(published_generation, PUBLIC_DATASETS[1])
    assert all(Path(file.path).exists() for file in pin.files)
    pin.close()
    reader.prepare(published_generation, PUBLIC_DATASETS[1]).close()
    assert not any(Path(file.path).exists() for file in pin.files)


@pytest.fixture
def relations(tmp_path, published):
    store, manifest, _ = published
    return tuple(
        (
            dataset,
            tuple(
                ApprovedFile(
                    str(store.root / ref.object.key),
                    ref.object.sha256,
                    ref.object.byte_count,
                    ref.row_count,
                )
                for ref in manifest.resources
                if ref.grain == dataset.grain
            ),
        )
        for dataset in PUBLIC_DATASETS
    )


def run_query(sql, relations, bounds=EXECUTION):
    request = QueryRead(sql, relations)
    result = subprocess.run(
        [sys.executable, "tests/fixtures/data_api/query_worker.py"],
        input=pickle.dumps((request, bounds, ENCODING)),
        capture_output=True,
        timeout=60,
        env={"PYTHONPATH": str(Path("src").resolve())},
    )
    assert result.returncode == 0, result.stderr.decode()
    output = pickle.loads(result.stdout)
    return output if isinstance(output, Exception) else json.loads(output.document)


def table(sql, relations):
    output = run_query(sql, relations)
    assert not isinstance(output, Exception), output
    return output["rows"]


def test_sql_semantics_over_views_joins_aggregates_ctes_subqueries_windows(relations):
    assert table(
        "SELECT n.period, count(*) FROM national n JOIN facilities f "
        "ON f.period = n.period GROUP BY n.period ORDER BY n.period",
        relations,
    ) == [["2026-09-01", "2"], ["2026-09-02", "2"]]
    assert table(
        "WITH t AS (SELECT period, sum(outage_mw) o FROM facilities GROUP BY period) "
        "SELECT period, sum(o) OVER (ORDER BY period) FROM t ORDER BY period",
        relations,
    ) == [["2026-09-01", "2.000000000000"], ["2026-09-02", "4.000000000000"]]
    assert table(
        "SELECT count(*) FROM generators WHERE facility IN "
        "(SELECT facility FROM facilities WHERE period = DATE '2026-09-02')",
        relations,
    ) == [["4"]]
    assert table(
        "SELECT row_number() OVER (PARTITION BY period ORDER BY generator DESC), "
        "generator FROM generators ORDER BY period, generator DESC LIMIT 2",
        relations,
    ) == [["1", "02"], ["2", "01"]]


def test_datasets_are_views_over_parquet_scans_with_no_base_table(relations):
    assert table(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name",
        relations,
    ) == [
        ["facilities", "VIEW"],
        ["generators", "VIEW"],
        ["national", "VIEW"],
    ]
    plan = table("EXPLAIN SELECT * FROM generators", relations)[0][1]
    assert "PARQUET_SCAN" in plan.upper() or "READ_PARQUET" in plan.upper()


@pytest.mark.parametrize(
    "template",
    [
        "SELECT * FROM read_parquet('{other}')",
        "COPY national TO '{out}'",
        "INSTALL httpfs",
        "ATTACH '{out}.db'",
        "SET enable_external_access = true",
        "SET allowed_paths = []",
        "SET lock_configuration = false",
        "SET memory_limit = '64GB'",
    ],
)
def test_user_sql_cannot_reach_other_files_or_change_the_engine(
    relations, tmp_path, published, template
):
    store, manifest, _ = published
    other = tmp_path / "unapproved.parquet"
    other.write_bytes((store.root / manifest.resources[0].object.key).read_bytes())
    sql = template.format(other=other, out=tmp_path / "out")
    output = run_query(sql, relations)
    assert isinstance(output, Exception), output
    assert not (tmp_path / "out").exists()


def test_tampered_or_missing_input_is_unavailable_before_any_scan(relations, tmp_path):
    dataset, files = relations[0]
    copy = tmp_path / "copy.parquet"
    copy.write_bytes(Path(files[0].path).read_bytes()[:-1])
    broken = ((dataset, (replace(files[0], path=str(copy)),)), *relations[1:])
    assert isinstance(run_query("SELECT 1 FROM national", broken), DataUnavailableError)
    empty = ((dataset, ()), *relations[1:])
    assert isinstance(run_query("SELECT 1", empty), DataUnavailableError)


def test_memory_exhaustion_fails_inside_bounds_and_locked_engine_still_spills(
    relations,
):
    tight = ExecutionBounds(20, 30, 64 * 1024**2, 16 * 1024**2, 1024**2)
    exhausted = run_query(
        "SELECT count(*) FROM (SELECT x::varchar g, count(*) c "
        "FROM range(30000000) t(x) GROUP BY g)",
        relations,
        tight,
    )
    assert isinstance(exhausted, AnalyticalResourceError)
    spilled = run_query(
        "SELECT count(*) FROM (SELECT row_number() OVER (ORDER BY random()) r "
        "FROM range(5000000) t(x)) WHERE r % 2 = 0",
        relations,
        ExecutionBounds(20, 30, 50 * 1024**2, 256 * 1024**2, 1024**2),
    )
    assert spilled["rows"] == [["2500000"]]
