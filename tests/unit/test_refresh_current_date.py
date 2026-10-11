"""HTTP admission dates with a controlled clock and no external services."""

from datetime import UTC, date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from outage_explorer.application.dto import RefreshAdmissionRequest, RequestAccess
from outage_explorer.application.errors import ForbiddenError, InvalidRequestError
from outage_explorer.bootstrap import build_data_services
from outage_explorer.domain.publication import RefreshConfiguration
from outage_explorer.infrastructure.clock import SystemClock
from outage_explorer.infrastructure.security import RandomSecurityMaterial
from outage_explorer.settings import refresh_settings


def service(monkeypatch, start="2026-04-02"):
    now = [datetime(2026, 10, 7, 23, 59, tzinfo=UTC)]
    clock_reads = []

    def read_clock(self):
        clock_reads.append(now[0])
        return now[0]

    monkeypatch.setattr(SystemClock, "now", read_clock)
    access = Mock()
    access.authenticate.return_value = RequestAccess(SimpleNamespace(id="admin"))
    access.require_roles.side_effect = lambda context, roles: context
    store = Mock()
    saved = {}
    store.replay.side_effect = lambda user, key: saved.get(key)

    def admit(user, key, config):
        config.validate_for_run(initial=False)
        run = SimpleNamespace(configuration=config)
        saved[key] = run
        return run

    store.admit.side_effect = admit
    services = build_data_services(
        access, store, RandomSecurityMaterial(), {"OUTAGE_REFRESH_START_DATE": start}
    )
    return services.refresh, now, clock_reads, access, store


def test_midnight_updates_new_run_but_replay_keeps_original(monkeypatch):
    refresh, now, reads, _, store = service(monkeypatch)
    assert not reads  # Startup must not freeze today's date.
    original = refresh.admit(
        refresh.authorize("token"), RefreshAdmissionRequest("a" * 16)
    )
    assert original.configuration.start == date(2026, 4, 2)
    assert original.configuration.end == date(2026, 10, 7)
    assert original.configuration.max_interval_days == 189
    assert original.configuration.source_interval_days == 189
    assert original.configuration.model_interval_days == 189
    now[0] += timedelta(days=1)
    assert (
        refresh.admit(refresh.authorize("token"), RefreshAdmissionRequest("a" * 16))
        is original
    )
    assert len(reads) == 1
    later = refresh.admit(refresh.authorize("token"), RefreshAdmissionRequest("b" * 16))
    assert later.configuration.end == date(2026, 10, 8)
    assert later.configuration.max_interval_days == 190
    assert original.configuration.end == date(2026, 10, 7)
    assert store.admit.call_count == 2


def test_today_uses_utc_independent_of_host_timezone(monkeypatch):
    refresh, now, _, _, _ = service(monkeypatch)
    now[0] = datetime(2026, 10, 7, 23, 30, tzinfo=timezone(timedelta(hours=-6)))
    assert refresh.admit(
        refresh.authorize("token"), RefreshAdmissionRequest("c" * 16)
    ).configuration.end == date(2026, 10, 8)


def test_future_start_fails_before_storage_admission(monkeypatch):
    refresh, _, _, _, store = service(monkeypatch, "2026-10-08")
    with pytest.raises(InvalidRequestError, match="after today"):
        refresh.admit(refresh.authorize("token"), RefreshAdmissionRequest("d" * 16))
    store.admit.assert_not_called()


def test_denial_does_not_resolve_clock(monkeypatch):
    refresh, _, reads, access, store = service(monkeypatch)
    access.require_roles.side_effect = ForbiddenError("denied")
    with pytest.raises(ForbiddenError):
        refresh.admit(refresh.authorize("token"), RefreshAdmissionRequest("f" * 16))
    assert not reads
    store.admit.assert_not_called()


@pytest.mark.parametrize(
    "key",
    [
        None,
        "a" * 15,
        "a" * 129,
        "a" * 15 + " ",
        "a" * 15 + "é",
    ],
)
def test_request_dto_rejects_invalid_idempotency_keys(key):
    with pytest.raises(InvalidRequestError, match="Invalid refresh request"):
        RefreshAdmissionRequest(key)


@pytest.mark.parametrize("key", ["a" * 16, "Z" * 128, "Ab09_-" * 3])
def test_valid_idempotency_keys_are_admitted(monkeypatch, key):
    refresh, _, reads, _, store = service(monkeypatch)
    run = refresh.admit(refresh.authorize("token"), RefreshAdmissionRequest(key))
    assert run.configuration.end == date(2026, 10, 7)
    store.admit.assert_called_once()
    assert len(reads) == 1


def test_programmatic_admission_authorizes_before_replay_or_configuration(monkeypatch):
    refresh, _, reads, access, store = service(monkeypatch)
    access.require_roles.side_effect = ForbiddenError("denied")
    with pytest.raises(ForbiddenError, match="denied"):
        refresh.admit(refresh.authorize("token"), RefreshAdmissionRequest("a" * 16))
    store.replay.assert_not_called()
    store.admit.assert_not_called()
    assert not reads


def test_admission_uses_decorator_principal_without_reauthorizing(monkeypatch):
    refresh, _, _, access, store = service(monkeypatch)
    request_access = RequestAccess(SimpleNamespace(id="verified-admin"))
    refresh.admit(request_access, RefreshAdmissionRequest("a" * 16))
    assert not access.mock_calls
    assert store.replay.call_args.args[0] == "verified-admin"
    assert store.admit.call_args.args[0] == "verified-admin"


def test_long_intervals_preserve_initial_policy_and_frozen_caps():
    config = RefreshConfiguration(
        start=date(2024, 1, 1),
        end=date(2026, 10, 7),
        max_interval_days=1011,
        source_interval_days=1011,
        model_interval_days=1011,
        candidate_seconds=1800,
        persistence_seconds=1800,
    )
    config.validate_for_run(initial=False)
    with pytest.raises(ValueError):
        config.validate_for_run(initial=True)
    with pytest.raises(ValueError):
        RefreshConfiguration.model_validate(
            config.model_dump() | {"source_interval_days": 183}
        ).validate_for_run(initial=False)


@pytest.mark.parametrize("value", ["20260402", "2026-4-2", "2026-02-30", ""])
def test_start_date_requires_canonical_iso(value):
    with pytest.raises(ValueError):
        refresh_settings({"OUTAGE_REFRESH_START_DATE": value})


def test_legacy_end_and_date_caps_do_not_limit_http_refresh():
    settings = refresh_settings(
        {
            "OUTAGE_REFRESH_START_DATE": "2026-04-02",
            "OUTAGE_REFRESH_END_DATE": "obsolete",
            "OUTAGE_REFRESH_MAX_INTERVAL_DAYS": "183",
            "OUTAGE_REFRESH_SOURCE_INTERVAL_DAYS": "183",
            "OUTAGE_REFRESH_MODEL_INTERVAL_DAYS": "183",
        }
    )
    assert settings.start_date == date(2026, 4, 2)
    assert settings.candidate_seconds == settings.persistence_seconds == 1800
    assert settings.s3_workers == 3
