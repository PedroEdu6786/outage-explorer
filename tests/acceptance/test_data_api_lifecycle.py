"""HTTP/process overlap under explicit controlled bounds, not Linux safety proof."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from outage_explorer.application.services.refresh_recovery import RefreshRecovery
from outage_explorer.domain.access import Role
from tests.integration import test_data_api_http as http
from tests.integration.test_connector_cli import Wire, row
from tests.integration.test_refresh_execution import composition
from tests.unit.test_data_api_contract import validator

database = http.database
system = http.system
browsing = http.browsing
queries = http.queries
app = http.app


def test_http_ack_overlap_publication_and_snapshot_survival(
    app, system, database, browsing, queries, tmp_path
):
    admin, headers = http.client_for(app, system)
    analyst, analyst_headers = http.client_for(app, system, Role.ANALYST)
    first = analyst.get("/api/datasets/national/preview?page_size=1").json
    retained = analyst.post(
        "/api/query?page_size=1",
        json={"sql": "SELECT period FROM national ORDER BY period"},
        headers=analyst_headers,
    ).json
    receipt = admin.post("/api/refresh", json={}, headers=headers)
    assert receipt.status_code == 202
    run_id = receipt.json["run_id"]
    assert system[0].get_run(run_id).status.value == "accepted"
    entered, release = Event(), Event()

    class BlockedSource(Wire):
        def handle_request(self, request):
            entered.set()
            assert release.wait(15)
            return super().handle_request(request)

    values = {
        grain: [row(grain, period="2026-09-03")]
        for grain in ("national", "facility", "generator")
    }
    worker = composition(
        database, tmp_path / "refresh-overlap", BlockedSource(values), browsing[5]
    )
    try:
        with ThreadPoolExecutor() as pool:
            future = pool.submit(worker.tick)
            assert entered.wait(5)
            running = admin.get(receipt.headers["Location"])
            validator("RefreshRun").validate(running.json)
            assert (
                running.json["status"] == "running"
                and running.json["started_at"] is not None
            )
            assert running.json["finished_at"] is None
            # Independent API construction and initiating-session loss do not own worker.
            system[1]._access.logout(system[2][Role.ADMIN])
            fresh_app = http.app_for(system, browsing, queries)
            fresh_analyst, _ = http.client_for(fresh_app, system, Role.ANALYST)
            assert fresh_analyst.get("/health").status_code == 200
            assert (
                fresh_analyst.get("/api/datasets").json["generation_id"]
                == first["generation_id"]
            )
            assert (
                fresh_analyst.post(
                    "/api/query", json={"sql": "SELECT 7"}, headers=analyst_headers
                ).status_code
                == 200
            )
            assert admin.get(receipt.headers["Location"]).status_code == 401
            release.set()
            finished = future.result(timeout=15)
        assert finished.status.value == "succeeded" and finished.finished_at is not None
        # Old sequences remain byte-for-byte stable after atomic all-grain publication.
        previous = fresh_analyst.get(
            "/api/datasets/national/preview",
            query_string={"cursor": first["page_cursor"]},
        )
        assert previous.json == first
        again = fresh_analyst.get(
            "/api/query", query_string={"query_id": retained["query_id"], "page": 1}
        )
        assert again.json == retained
        active = fresh_analyst.get("/api/datasets").json
        assert active["generation_id"] != first["generation_id"]
        assert len(active["datasets"]) == 3
        calls = tuple(browsing[5].calls)
        assert RefreshRecovery(system[0]).execute(run_id).status.value == "succeeded"
        assert tuple(browsing[5].calls) == calls
    finally:
        release.set()
        worker.close()


def test_http_busy_slot_keeps_health_and_status_available(app, system, queries):
    client, headers = http.client_for(app, system)
    reservation = queries[4].reserve()
    try:
        result = client.post("/api/query", json={"sql": "SELECT 1"}, headers=headers)
        assert (
            result.status_code == 503 and result.json["error"]["code"] == "query_busy"
        )
        assert result.headers["Retry-After"] == "3"
        assert client.get("/health").status_code == 200
        assert client.get("/api/refresh/latest").status_code == 200
        assert not queries[3].calls
    finally:
        reservation.close()
