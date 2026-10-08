"""Typed defaults and file overrides fail safely before connector construction."""

import json
from dataclasses import FrozenInstanceError
from unittest.mock import Mock, patch

import pytest

from outage_explorer.application.dto import ConnectorInput
from outage_explorer.application.errors import ConnectorConfigurationError
from outage_explorer.bootstrap import execute_connector
from outage_explorer.settings import CONFIG_MAX_BYTES, connector_settings
from tests.integration.test_connector_cli import SECRET, configuration, environment


@pytest.fixture
def config_path(tmp_path):
    return tmp_path / "connector.json"


def settings(config_path=None, **changes):
    return connector_settings(
        **{
            "start": "2026-09-01",
            "end": "2026-09-02",
            "staging": "local",
            "prior": None,
            "environment": environment(),
            "config_path": None if config_path is None else str(config_path),
        }
        | changes
    )


def test_only_credentials_required_for_typed_defaults():
    value = settings()
    assert value.source.interval_days == 183
    assert value.source.page_rows == 500
    assert value.source.rows == 100_000
    assert value.source.pages == 250
    assert value.source.requests == 500
    assert value.model.incoming_rows == value.model.prior_rows == 100_000
    assert value.artifact.total_bytes == 256_000_000
    assert value.model.output_rows == 100_000
    assert value.report_bytes == 1_000_000
    with pytest.raises(FrozenInstanceError):
        value.source.rows = 1


def test_legacy_budget_environment_variables_do_not_override_defaults():
    env = environment() | {
        "OUTAGE_CONNECTOR_SOURCE_BOUNDS": '{"page_rows":1}',
        "OUTAGE_CONNECTOR_ARTIFACT_BOUNDS": "not json",
        "OUTAGE_CONNECTOR_MODEL_BOUNDS": '{"output_rows":1}',
        "OUTAGE_CONNECTOR_REPORT_BYTES": "1",
    }
    assert settings(environment=env) == settings()


def test_partial_file_overrides_keep_other_defaults_and_do_not_mutate_them(config_path):
    config_path.write_text(
        json.dumps(
            {
                "source": {"page_rows": 10},
                "artifact": {"batch_rows": 5},
                "model": {"interval_days": 7},
                "report_bytes": 2_000_000,
            }
        )
    )
    value = settings(config_path)
    assert value.source.page_rows == 10 and value.source.rows == 100_000
    assert value.artifact.batch_rows == 5 and value.artifact.objects == 10_000
    assert value.model.interval_days == 7 and value.model.output_rows == 100_000
    assert value.report_bytes == 2_000_000
    assert settings().source.page_rows == 500


@pytest.mark.parametrize("document", [{}, {"source": {}, "artifact": {}, "model": {}}])
def test_empty_or_complete_file_is_supported(config_path, document):
    config_path.write_text(json.dumps(document))
    assert settings(config_path) == settings()


def test_explicit_small_profile_keeps_its_limits(config_path):
    profile = configuration()
    config_path.write_text(json.dumps(profile))
    value = settings(config_path)
    assert value.source.interval_days == 30
    assert value.source.page_rows == 2
    assert value.source.elapsed_seconds == 60
    assert value.artifact.total_bytes == 100_000_000
    assert value.model.interval_days == 30
    assert value.model.output_rows == 10_000


def test_file_run_arguments_and_explicit_flag_precedence(config_path):
    config_path.write_text(
        json.dumps(
            {
                "start": "2026-09-03",
                "end": "2026-09-04",
                "staging": "from-file",
                "prior": "prior-report.json",
            }
        )
    )
    value = settings(config_path, start=None, end=None, staging=None)
    assert value.start.isoformat() == "2026-09-03"
    assert value.end.isoformat() == "2026-09-04"
    assert value.staging == "from-file"
    assert value.prior_resources == "prior-report.json"
    explicit = settings(config_path, prior="explicit-report.json")
    assert explicit.start.isoformat() == "2026-09-01"
    assert explicit.end.isoformat() == "2026-09-02"
    assert explicit.staging == "local"
    assert explicit.prior_resources == "explicit-report.json"


@pytest.mark.parametrize("name", ["start", "end", "staging"])
def test_run_arguments_required_from_file_or_flags(name):
    with pytest.raises(ValueError, match="Invalid connector configuration"):
        settings(**{name: None})


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-09-03", "2026-09-01"),
        ("secret", "2026-09-01"),
        ("20260901", "2026-09-01"),
        ("2026-02-30", "2026-09-01"),
    ],
)
def test_dates_are_explicit_canonical_and_ordered(start, end):
    with pytest.raises(ValueError, match="Invalid connector configuration"):
        settings(start=start, end=end)


@pytest.mark.parametrize("prior", ["", " ", "bad\x00path"])
def test_nonempty_local_metadata_path_required(prior):
    with pytest.raises(ValueError, match="Invalid connector configuration"):
        settings(prior=prior)


@pytest.mark.parametrize(
    "document",
    [
        "[]",
        "null",
        '"string"',
        "not json",
        '{"source":',
        '{"source":{"unknown":1}}',
        '{"artifact":{"unknown":1}}',
        '{"model":{"unknown":1}}',
        '{"unknown":1}',
        '{"source":{},"source":{}}',
        '{"source":{"rows":1,"rows":2}}',
        '{"EIA_API_KEY":"secret"}',
        '{"api_key":"secret"}',
        '{"source":{"api_key":"secret"}}',
        '{"start":null}',
        '{"end":12}',
        '{"staging":[]}',
        '{"prior":null}',
        '{"source":null}',
        '{"artifact":[]}',
        '{"model":3}',
    ],
)
def test_invalid_json_shape_duplicates_and_unknown_fields_rejected(
    config_path, document
):
    config_path.write_text(document)
    with pytest.raises(ValueError, match="^Invalid connector configuration$"):
        settings(config_path)


@pytest.mark.parametrize(
    "section,field",
    [
        ("source", "rows"),
        ("artifact", "objects"),
        ("model", "output_rows"),
        (None, "report_bytes"),
    ],
)
@pytest.mark.parametrize(
    "value", [True, False, 0, -1, 1.5, "10", None, [], {}, float("nan"), float("inf")]
)
def test_budgets_are_positive_exact_integers(config_path, section, field, value):
    document = {field: value} if section is None else {section: {field: value}}
    config_path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Invalid connector configuration"):
        settings(config_path)


@pytest.mark.parametrize(
    "contents", [b"\xff", b" " * (CONFIG_MAX_BYTES + 1), b"[" * 2000 + b"]" * 2000]
)
def test_file_encoding_size_and_recursion_are_bounded(config_path, contents):
    config_path.write_bytes(contents)
    with pytest.raises(ValueError, match="Invalid connector configuration"):
        settings(config_path)


def test_missing_directory_and_unreadable_file_errors_are_sanitized(config_path):
    for path in (config_path, config_path.parent):
        with pytest.raises(ValueError, match="^Invalid connector configuration$"):
            settings(path)
    config_path.write_text("{}")
    with patch("pathlib.Path.open", side_effect=PermissionError(SECRET)):
        with pytest.raises(ValueError, match="^Invalid connector configuration$"):
            settings(config_path)


@pytest.mark.parametrize(
    "env",
    [{}, {"EIA_API_KEY": ""}, {"EIA_API_KEY": "secret\n"}, {"EIA_API_KEY": "s" * 4097}],
)
def test_key_is_required_and_validated(env):
    with pytest.raises(ValueError, match="Invalid connector configuration"):
        settings(environment=env)


@pytest.mark.parametrize(
    "document",
    [
        {"source": {"interval_days": 1}},
        {"model": {"interval_days": 1}},
        {"source": {"page_rows": 5001}},
        {"source": {"field_bytes": 63}},
        {"model": {"field_chars": 63}},
        {"report_bytes": 0},
        {"unknown": 1},
    ],
)
def test_bootstrap_validates_before_any_construction(tmp_path, config_path, document):
    config_path.write_text(json.dumps(document))
    wire = Mock()
    with (
        patch(
            "outage_explorer.bootstrap.LocalParquetStore",
            side_effect=AssertionError("storage"),
        ),
        patch(
            "outage_explorer.bootstrap.httpx.HTTPTransport",
            side_effect=AssertionError("transport"),
        ),
    ):
        with pytest.raises(
            ConnectorConfigurationError, match="^Invalid connector configuration$"
        ):
            execute_connector(
                ConnectorInput(
                    "2026-09-01",
                    "2026-09-02",
                    str(tmp_path / "new"),
                    config_path=str(config_path),
                ),
                environment=environment(),
                transport=wire,
            )
    wire.close.assert_called_once()
    assert not (tmp_path / "new").exists()


def test_secret_not_in_settings_representation_or_errors():
    assert SECRET not in repr(settings())
    with pytest.raises(ValueError) as error:
        settings(staging=SECRET)
    assert SECRET not in str(error.value)


def test_default_interval_overrun_still_fails_before_construction(tmp_path):
    wire = Mock()
    root = tmp_path / "never-created"
    with (
        patch(
            "outage_explorer.bootstrap.LocalParquetStore",
            side_effect=AssertionError("storage"),
        ),
        patch(
            "outage_explorer.bootstrap.httpx.HTTPTransport",
            side_effect=AssertionError("transport"),
        ),
        pytest.raises(ConnectorConfigurationError),
    ):
        execute_connector(
            ConnectorInput("2026-04-02", "2026-10-02", str(root)),
            environment=environment(),
            transport=wire,
        )
    wire.close.assert_called_once()
    assert not root.exists()


@pytest.mark.parametrize("field", ["endpoint_workers", "s3_workers"])
@pytest.mark.parametrize("value", [0, -1, 4, True, "3"])
def test_worker_counts_fail_closed(config_path, field, value):
    config_path.write_text(json.dumps({"workers": {field: value}}))
    with pytest.raises(ValueError, match="Invalid connector configuration"):
        settings(config_path)


def test_sequential_defaults_and_independent_worker_overrides(config_path):
    default = settings()
    assert default.workers.endpoint_workers == 1
    assert default.workers.s3_workers == 3
    config_path.write_text(
        json.dumps({"workers": {"endpoint_workers": 3, "s3_workers": 2}})
    )
    configured = settings(config_path)
    assert configured.workers.endpoint_workers == 3
    assert configured.workers.s3_workers == 2


def test_explicit_fetch_and_transfer_counts_override_json(config_path):
    config_path.write_text(
        json.dumps({"workers": {"page_workers": 1, "s3_workers": 1}})
    )
    value = connector_settings(
        "2026-09-01", "2026-09-02", "local", None, environment(), str(config_path), 3, 2
    )
    assert value.workers.page_workers == 3 and value.workers.s3_workers == 2
    assert value.workers.endpoint_workers == 1


@pytest.mark.parametrize("count", [0, 4, True, "3"])
def test_invalid_page_worker_count_rejected_before_storage(config_path, count):
    config_path.write_text(json.dumps({"workers": {"page_workers": count}}))
    with pytest.raises(ValueError):
        settings(config_path)


def test_resource_s3_default_three_preserves_shared_defaults_and_aggregate_limits():
    from outage_explorer.settings import (
        ResourceWorkerSettings,
        WorkerSettings,
        resource_worker_settings,
    )

    current = WorkerSettings()
    resource = resource_worker_settings({})
    assert isinstance(resource, ResourceWorkerSettings) and resource.s3_workers == 3
    assert current.s3_workers == 1
    assert (resource.memory_bytes, resource.temporary_bytes) == (
        current.memory_bytes,
        current.temporary_bytes,
    )
    assert resource.endpoint_workers == resource.page_workers == 1


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_resource_worker_flags_override_json_without_replacing_other_defaults(workers):
    from outage_explorer.settings import resource_worker_settings

    result = resource_worker_settings(
        {"workers": {"s3_workers": 1, "page_workers": 2}}, s3=workers
    )
    assert result.s3_workers == workers and result.page_workers == 2
    assert (
        resource_worker_settings({"workers": {"s3_workers": workers}}).s3_workers
        == workers
    )


@pytest.mark.parametrize("invalid", [0, 4, True, 1.0, "2"])
def test_resource_worker_invalid_override_rejected(invalid):
    from outage_explorer.settings import resource_worker_settings

    with pytest.raises(ValueError):
        resource_worker_settings({}, s3=invalid)
    with pytest.raises(ValueError):
        resource_worker_settings({"workers": {"s3_workers": invalid}})


def test_eia_backoff_and_pacing_defaults_and_json_overrides(config_path):
    defaults = settings().source
    assert (defaults.attempts, defaults.timeout_seconds) == (5, 30)
    assert (defaults.backoff_base_seconds, defaults.backoff_seconds) == (10, 120)
    assert defaults.request_interval_milliseconds == 500
    config_path.write_text(
        json.dumps(
            {
                "source": {
                    "backoff_base_seconds": 20,
                    "backoff_seconds": 180,
                    "request_interval_milliseconds": 2000,
                }
            }
        )
    )
    value = settings(config_path).source
    assert (value.backoff_base_seconds, value.backoff_seconds) == (20, 180)
    assert value.request_interval_milliseconds == 2000


@pytest.mark.parametrize(
    "field", ["backoff_base_seconds", "request_interval_milliseconds"]
)
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1000", None])
def test_eia_pacing_and_backoff_require_positive_integers(config_path, field, value):
    config_path.write_text(json.dumps({"source": {field: value}}))
    with pytest.raises(ValueError, match="Invalid connector configuration"):
        settings(config_path)
