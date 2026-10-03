"""Application use-case tests with ports replaced; no Flask, storage or AWS."""

from outage_explorer.application.dto import EvidenceBundle, ReportLocations
from outage_explorer.application.services.evidence import VerifyNationalBaseline
from outage_explorer.domain.national import SourceRecord


class RecordedRows:
    def __init__(self, rows):
        self.rows = rows
        self.references = []

    def load(self, reference):
        self.references.append(reference)
        return EvidenceBundle(
            "{}",
            "test-only",
            (),
            tuple(SourceRecord(i, row) for i, row in enumerate(self.rows)),
            (),
        )


class CaptureReport:
    def __init__(self):
        self.writes = []

    def write(self, report, destination):
        self.writes.append((report, destination))
        return ReportLocations("report.json", "report.md")


def test_empty_retrieval_is_visible_as_30_gaps_and_reported_once():
    evidence = RecordedRows([])
    writer = CaptureReport()
    service = VerifyNationalBaseline(evidence, writer)
    assert evidence.references == []
    assert writer.writes == []
    assert service.run("fixed-evidence", "destination") == ReportLocations(
        "report.json", "report.md"
    )
    assert evidence.references == ["fixed-evidence"]
    assert len(writer.writes) == 1
    report, destination = writer.writes[0]
    assert destination == "destination"
    assert len(report.coverage) == 30
    assert all(item.result is None for item in report.coverage)
    assert dict(report.counts)["received"] == 0


def test_multiple_invalid_fields_count_one_excluded_row():
    report = VerifyNationalBaseline(
        RecordedRows([{"period": "2026-09-02"}]), CaptureReport()
    ).verify("synthetic")
    assert dict(report.counts)["excluded"] == 1
    assert dict(report.reason_counts) == {"missing": 6}
    assert report.coverage[0].excluded_positions == ()
    assert report.coverage[1].excluded_positions == (0,)
