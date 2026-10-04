"""Thin contributor command; parsing help never constructs a connector."""

import argparse
from collections.abc import Callable, Sequence
from typing import Never

from outage_explorer.application.dto import ConnectorInput, ConnectorResult
from outage_explorer.application.errors import ConnectorConfigurationError


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        # argparse normally echoes supplied arguments, which may contain secrets.
        self.exit(2, "failed arguments; no publication\n")


def run(
    execute: Callable[[ConnectorInput], ConnectorResult],
    argv: Sequence[str] | None = None,
) -> int:
    parser = _Parser(
        description="Build a verified local candidate; never publishes an active generation."
    )
    parser.add_argument(
        "--config", help="JSON configuration file; omitted limits use defaults"
    )
    parser.add_argument("--start", help="Inclusive YYYY-MM-DD; overrides config")
    parser.add_argument("--end", help="Inclusive YYYY-MM-DD; overrides config")
    parser.add_argument(
        "--staging",
        help="Local immutable objects and separate run reports; overrides config",
    )
    parser.add_argument(
        "--prior",
        help="Exact prior manifest SHA256:BYTE_COUNT in the same staging store; overrides config",
    )
    args = parser.parse_args(argv)
    try:
        result = execute(
            ConnectorInput(args.start, args.end, args.staging, args.prior, args.config)
        )
    except ConnectorConfigurationError:
        print("failed configuration; no publication")
        return 2
    except KeyboardInterrupt:
        print("failed interrupted; no publication")
        return 130
    except Exception:
        print("failed internal; no publication")
        return 1
    report = result.report
    print(f"{report.outcome} run={report.run_id}; no publication")
    if report.error is not None:
        print(f"error={report.error}; report_written={result.report_written}")
    if report.manifest is not None:
        print(f"manifest={report.manifest.sha256}:{report.manifest.byte_count}")
    if report.error == "interrupted":
        return 130
    return 1 if report.outcome == "failed" else 0
