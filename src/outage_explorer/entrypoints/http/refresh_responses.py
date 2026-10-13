"""Refresh response DTOs own HTTP envelopes, statuses and headers."""

from outage_explorer.application.refresh_responses import (
    RefreshAdmissionResult,
    RefreshRunResult,
)
from outage_explorer.entrypoints.http.responses import ResponseData


class RefreshAdmissionResponse(RefreshAdmissionResult):
    def build(self) -> ResponseData:
        status_url = "/api/refresh/" + self.run_id
        return ResponseData(
            body={
                "run_id": self.run_id,
                "status": self.status,
                "effective_interval": {
                    "start_date": self.start_date,
                    "end_date": self.end_date,
                },
                "status_url": status_url,
            },
            status=200 if self.terminal else 202,
            headers={"Location": status_url, "Retry-After": "3"},
        )


class RefreshLatestResponse(RefreshRunResult):
    def build(self) -> ResponseData:
        return ResponseData(body={"run": self.run})


class RefreshStatusResponse(RefreshRunResult):
    def build(self) -> ResponseData:
        if self.run is None:
            return ResponseData(
                body={
                    "error": {
                        "code": "refresh_unavailable",
                        "message": "Refresh unavailable",
                    }
                },
                status=404,
            )
        return ResponseData(body=self.run)
