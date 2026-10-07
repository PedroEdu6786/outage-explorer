"""HTTP admission dates with a controlled clock and no external services."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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
    access.authorize.return_value = SimpleNamespace(
        principal=SimpleNamespace(id="admin")
    )
    store = Mock()
    saved = {}
    store.replay.side_effect = lambda user, key, identity: saved.get(key)

    def admit(user, key, identity, config):
        config.validate(initial=False)
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
    original = refresh.admit("token", "a" * 16, {})
    assert original.configuration.start == date(2026, 4, 2)
    assert original.configuration.end == date(2026, 10, 7)
    assert original.configuration.max_interval_days == 189
    assert original.configuration.source_interval_days == 189
    assert original.configuration.model_interval_days == 189
    now[0] += timedelta(days=1)
    assert refresh.admit("token", "a" * 16, {}) is original
    assert len(reads) == 1
    later = refresh.admit("token", "b" * 16, {})
    assert later.configuration.end == date(2026, 10, 8)
    assert later.configuration.max_interval_days == 190
    assert original.configuration.end == date(2026, 10, 7)
    assert store.admit.call_count == 2


def test_today_uses_utc_independent_of_host_timezone(monkeypatch):
    refresh, now, _, _, _ = service(monkeypatch)
    now[0] = datetime(2026, 10, 7, 23, 30, tzinfo=timezone(timedelta(hours=-6)))
    assert refresh.admit("token", "c" * 16, {}).configuration.end == date(2026, 10, 8)


def test_future_start_fails_before_storage_admission(monkeypatch):
    refresh, _, _, _, store = service(monkeypatch, "2026-10-08")
    with pytest.raises(InvalidRequestError, match="after today"):
        refresh.admit("token", "d" * 16, {})
    store.admit.assert_not_called()


def test_denial_and_caller_overrides_do_not_resolve_clock(monkeypatch):
    refresh, _, reads, access, store = service(monkeypatch)
    with pytest.raises(InvalidRequestError):
        refresh.admit("token", "e" * 16, {"end": "2026-10-01"})
    access.authorize.side_effect = ForbiddenError("denied")
    with pytest.raises(ForbiddenError):
        refresh.admit("token", "f" * 16, {})
    assert not reads
    store.admit.assert_not_called()


def test_long_intervals_preserve_initial_policy_and_frozen_caps():
    config = RefreshConfiguration(
        date(2024, 1, 1), date(2026, 10, 7), 1011, 1011, 1011, 1800, 1800
    )
    config.validate(initial=False)
    with pytest.raises(ValueError):
        config.validate(initial=True)
    with pytest.raises(ValueError):
        replace(config, source_interval_days=183).validate(initial=False)


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
