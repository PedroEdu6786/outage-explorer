from datetime import UTC, datetime

from outage_explorer.application.services.health import HealthService


def test_health_uses_current_time_on_each_check_without_flask():
    times = iter([datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)])

    class AdvancingClock:
        def now(self):
            return next(times)

    service = HealthService(AdvancingClock())

    first = service.check()
    second = service.check()

    assert first.status == "ok"
    assert first.service == "outage-explorer"
    assert first.checked_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert second.checked_at == datetime(2026, 10, 2, tzinfo=UTC)
