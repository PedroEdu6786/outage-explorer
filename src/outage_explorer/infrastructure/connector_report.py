"""Bounded, atomic, separate-run JSON reports without raw exception text."""

import json
import os
import re
import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path

from outage_explorer.application.dto import ResourceReport
from outage_explorer.application.errors import ConnectorReportError


class LocalConnectorReports:
    def __init__(self, root: Path, run_id: str, byte_limit: int) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", run_id) or byte_limit <= 0:
            raise ConnectorReportError("Invalid report configuration")
        self.root, self.limit = root / "runs" / run_id, byte_limit
        self._used = self._sequence = 0

    def progress(self, report: ResourceReport) -> None:
        self._write(f"progress-{self._sequence:02d}.json", report)
        self._sequence += 1

    def finish(self, report: ResourceReport) -> None:
        self._write("report.json", report)

    def _write(self, name: str, report: ResourceReport) -> None:
        temporary: Path | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            encoder = json.JSONEncoder(
                sort_keys=True, separators=(",", ":"), default=_date
            )
            count = 0
            with tempfile.NamedTemporaryFile(
                dir=self.root, prefix=".report-", delete=False
            ) as target:
                temporary = Path(target.name)
                for chunk in encoder.iterencode(asdict(report)):
                    data = chunk.encode()
                    count += len(data)
                    if self._used + count > self.limit:
                        raise ConnectorReportError("Report byte budget exhausted")
                    target.write(data)
                target.flush()
                os.fsync(target.fileno())
            os.link(temporary, self.root / name)
            self._used += count
        except (OSError, ValueError, TypeError) as error:
            raise ConnectorReportError("Cannot persist connector report") from error
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # Cleanup cannot turn an already-linked final report into
                    # an apparent failed write; an orphan temp is not an outcome.
                    pass


def _date(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError("Unsupported report value")
