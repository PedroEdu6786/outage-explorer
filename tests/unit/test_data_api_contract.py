import copy
import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.infrastructure.query_results.encoding import column_descriptors

ROOT = Path(__file__).parents[2] / "docs/specs/data-api"
CONTRACT = json.loads((ROOT / "openapi.json").read_text())
FIXTURES = json.loads((ROOT / "fixtures.json").read_text())["fixtures"]


def validator(name):
    return Draft202012Validator(
        {"$ref": f"#/components/schemas/{name}", "components": CONTRACT["components"]},
        format_checker=FormatChecker(),
    )


def test_seven_operations_are_implemented_and_all_have_fixtures():
    operations = {
        operation["operationId"]: operation
        for path in CONTRACT["paths"].values()
        for operation in path.values()
    }
    assert len(operations) == 7
    assert {fixture["operation_id"] for fixture in FIXTURES} == operations.keys()
    for operation in operations.values():
        assert operation["x-implementation-status"] == "implemented"
        assert operation["security"] == [{"SessionCookie": []}]
    assert (
        CONTRACT["components"]["securitySchemes"]["SessionCookie"]["name"]
        == "__Host-outage_session"
    )
    for schema in CONTRACT["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)
    for fixture in FIXTURES:
        responses = operations[fixture["operation_id"]]["responses"]
        assert str(fixture["status"]) in responses
        assert (
            fixture["schema"]
            == responses[str(fixture["status"])]["content"]["application/json"][
                "schema"
            ]["$ref"].split("/")[-1]
        )
        assert fixture["headers"]["Cache-Control"] == "no-store"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture["name"])
def test_every_client_fixture_validates(fixture):
    validator(fixture["schema"]).validate(fixture["body"])
    if "error" in fixture["body"]:
        error = fixture["body"]["error"]
        assert "csrf_failed" != error["code"]
        if "retry_after_seconds" in error:
            assert (
                str(error["retry_after_seconds"]) == fixture["headers"]["Retry-After"]
            )
        if error["code"] == "result_capacity_exhausted":
            assert fixture["status"] in (429, 503)


def test_catalog_matches_shared_ordered_projection_and_role_matrix():
    datasets = {d.id: d for d in PUBLIC_DATASETS}
    for fixture in FIXTURES:
        if fixture["schema"] == "Catalog":
            public = fixture["body"]["datasets"]
            assert [d["id"] for d in public] == (
                ["national"] if fixture["name"] == "catalog_viewer" else list(datasets)
            )
            for descriptor in public:
                assert descriptor["columns"] == column_descriptors(
                    datasets[descriptor["id"]].columns
                )
                assert descriptor["id"] == descriptor["sql_name"]
        if fixture["schema"] == "Preview":
            body = fixture["body"]
            assert body["columns"] == column_descriptors(
                datasets[body["dataset"]].columns
            )
            assert body["has_more"] is (body["next_cursor"] is not None)


def test_row_alignment_pagination_and_continuation_invariants():
    by_name = {f["name"]: f["body"] for f in FIXTURES}
    for fixture in FIXTURES:
        body = fixture["body"]
        if fixture["schema"] not in ("Preview", "QueryResult"):
            continue
        assert [col["index"] for col in body["columns"]] == list(
            range(len(body["columns"]))
        )
        assert all(len(row) == len(body["columns"]) for row in body["rows"])
        if fixture["schema"] == "QueryResult":
            assert body["total_pages"] == max(
                1, math.ceil(body["retained_row_count"] / body["page_size"])
            )
            assert body["has_more"] is (body["page"] < body["total_pages"])
            assert body["truncated"] is (body["truncation_reason"] is not None)
    assert by_name["query_revisit"] == by_name["query_first"]
    assert by_name["preview_revisit"] == by_name["preview_first"]
    assert by_name["query_second"] == by_name["query_direct_page"]
    assert by_name["query_empty"]["truncation_reason"] is None
    assert by_name["query_oversized_first"]["truncation_reason"] == "byte_limit"


def test_refresh_states_are_consistent_and_all_grains_present():
    runs = [f["body"] for f in FIXTURES if f["schema"] == "RefreshRun"]
    mapping = {
        "accepted": "pending",
        "running": "pending",
        "publication_unknown": "unknown",
        "succeeded": "published",
        "retained": "not_published",
        "failed": "not_published",
        "interrupted": "not_published",
    }
    assert {run["status"] for run in runs} == mapping.keys()
    for run in runs:
        assert run["publication"]["state"] == mapping[run["status"]]
        assert [d["id"] for d in run["datasets"]] == [
            "national",
            "facilities",
            "generators",
        ]
        assert (run["publication"]["generation_id"] is not None) is (
            run["status"] == "succeeded"
        )
        for dataset in run["datasets"]:
            quality = dataset["quality"]
            if quality:
                assert quality["received_rows"] == sum(
                    quality[k]
                    for k in [
                        "selected_rows",
                        "excluded_rows",
                        "duplicates_collapsed",
                        "superseded_rows",
                    ]
                )
                assert quality["modeled_rows"] == sum(
                    quality[k]
                    for k in [
                        "selected_rows",
                        "retained_invalid_rows",
                        "retained_absent_rows",
                        "carried_outside_interval_rows",
                    ]
                )
    assert any(
        f["name"] == "latest_no_run" and f["body"] == {"run": None} for f in FIXTURES
    )


@pytest.mark.parametrize(
    "change",
    [{"encoding": "number-or-special-string"}, {"precision": 38}, {"children": []}],
)
def test_type_contract_rejects_incompatible_metadata(change):
    column = copy.deepcopy(
        next(f["body"]["columns"][0] for f in FIXTURES if f["name"] == "query_first")
    )
    column.update(change)
    assert list(validator("Column").iter_errors(column))


def test_request_contract_rejects_refresh_overrides_and_sql_body_pagination():
    assert list(validator("RefreshRequest").iter_errors({"start_date": "2026-01-01"}))
    assert list(validator("QueryRequest").iter_errors({"sql": "SELECT 1", "page": 2}))


def test_corrected_examples_are_consistent():
    by_name = {f["name"]: f for f in FIXTURES}
    for name in ("query_first", "query_direct_page", "query_second", "query_revisit"):
        assert [col["name"] for col in by_name[name]["body"]["columns"]] == [
            "x",
            "x_copy",
        ]
    assert [
        col["name"] for col in by_name["query_duplicate_labels"]["body"]["columns"]
    ] == ["x", "x"]
    row_limit = by_name["query_row_limit"]["body"]
    assert row_limit["retained_row_count"] == row_limit["limits"]["max_rows"] == 1000
    assert len(row_limit["rows"]) == row_limit["page_size"] == 1
    assert by_name["query_reference_free"]["body"]["generation_id"] is None
