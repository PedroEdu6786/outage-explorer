"""Public DTO projections; private durable identities never cross transport."""

from datetime import datetime
from json import loads

from outage_explorer.domain.publication import RefreshRun


def timestamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def refresh_payload(run: RefreshRun) -> dict[str, object]:
    reports = (
        {}
        if run.quality_json is None
        else {item["dataset"]: item for item in loads(run.quality_json)["datasets"]}
    )
    datasets = []
    for grain, public in (
        ("national", "national"),
        ("facility", "facilities"),
        ("generator", "generators"),
    ):
        report = reports.get(grain)
        quality = None
        if report is not None and report.get("selected") is not None:
            quality = {
                public_name: report.get(stored)
                for public_name, stored in (
                    ("received_rows", "received"),
                    ("selected_rows", "selected"),
                    ("excluded_rows", "excluded"),
                    ("duplicates_collapsed", "duplicate"),
                    ("superseded_rows", "superseded"),
                    ("retained_invalid_rows", "retained_invalid"),
                    ("retained_absent_rows", "retained_absent"),
                    ("carried_outside_interval_rows", "carried_outside_interval"),
                    ("modeled_rows", "output"),
                )
            }
            quality["retained_entire_dataset"] = (
                report["received"] > 0 and report["received"] == report["excluded"]
            )
            quality["exclusion_reasons"] = [
                {"code": code, "count": count}
                for code, count in sorted(
                    (report.get("exclusion_reasons") or {}).items()
                )
            ]
        status = "pending" if run.status.value == "accepted" else "processing"
        if run.status.terminal:
            status = (
                "failed"
                if run.status.value in {"failed", "interrupted"}
                else "retained"
                if quality is not None and quality["retained_entire_dataset"]
                else "succeeded"
            )
        datasets.append(
            {
                "id": public,
                "status": status,
                "coverage": None if report is None else report.get("coverage"),
                "quality": quality,
            }
        )
    return {
        "run_id": run.id,
        "status": run.status.value,
        "stage": run.stage.value,
        "effective_interval": {
            "start_date": run.configuration.start.isoformat(),
            "end_date": run.configuration.end.isoformat(),
        },
        "accepted_at": timestamp(run.admitted_at),
        "started_at": timestamp(run.started_at),
        "finished_at": timestamp(run.finished_at),
        "datasets": datasets,
        "publication": {
            "state": run.publication.value,
            "generation_id": run.generation_id,
            "previous_generation_id": run.base_generation_id,
            "no_publication_reason": run.no_publication_reason,
        },
        "failure": None
        if run.failure is None
        else {"code": run.failure, "message": "Refresh did not complete"},
    }


def query_error_details(identity: object) -> dict[str, object] | None:
    from outage_explorer.domain.query_results import ResultIdentity

    return (
        {"query_id": identity.id, "expires_at": timestamp(identity.expires_at)}
        if isinstance(identity, ResultIdentity)
        else None
    )
