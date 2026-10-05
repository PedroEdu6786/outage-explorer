"""Thin contributor command; parsing help never constructs a connector."""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from typing import Never

from outage_explorer.application.dto import (
    ConnectorArtifactInput,
    ConnectorInput,
    ConnectorResult,
)
from outage_explorer.application.errors import (
    ConnectorConfigurationError,
    ConnectorDependencyError,
)
from outage_explorer.application.ports.connector import DurableConnectorReceipt
from outage_explorer.application.services.connector_artifacts import (
    DurableCandidateResult,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        # argparse normally echoes supplied arguments, which may contain secrets.
        self.exit(2, "failed arguments; no publication\n")


def run(
    execute: Callable[[ConnectorInput], ConnectorResult],
    argv: Sequence[str] | None = None,
    *,
    execute_artifacts: Callable[[ConnectorArtifactInput], DurableConnectorReceipt]
    | None = None,
    execute_durable: Callable[[ConnectorInput], DurableCandidateResult] | None = None,
) -> int:
    parser = _Parser(
        description="Build and store a verified candidate in S3 by default; never publishes an active generation."
    )
    parser.add_argument(
        "--config", help="JSON configuration file; omitted limits use defaults"
    )
    parser.add_argument(
        "--fetch-workers",
        type=int,
        help="Concurrent pages per endpoint,1–3; overrides JSON",
    )
    parser.add_argument(
        "--s3-workers", type=int, help="Concurrent S3 transfers,1–3; overrides JSON"
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
    parser.add_argument(
        "--operation",
        choices=("candidate", "persist", "recover"),
        default="candidate",
        help="Explicit local build or durable graph transfer",
    )
    parser.add_argument(
        "--manifest", help="Exact manifest SHA256:BYTE_COUNT for persist/recover"
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Build a local candidate without S3; candidate operation only",
    )
    args = parser.parse_args(argv)
    if any(
        value is not None and not 1 <= value <= 3
        for value in (args.fetch_workers, args.s3_workers)
    ):
        parser.error("Invalid worker count")
    # Configure only this command's diagnostics. Leave root/SDK/wire loggers alone.
    logger = logging.getLogger("outage_explorer.connector")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    )
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        return _execute(execute, args, execute_artifacts, execute_durable)
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def _execute(
    execute: Callable[[ConnectorInput], ConnectorResult],
    args: argparse.Namespace,
    execute_artifacts: Callable[[ConnectorArtifactInput], DurableConnectorReceipt]
    | None,
    execute_durable: Callable[[ConnectorInput], DurableCandidateResult] | None,
) -> int:
    logger = logging.getLogger("outage_explorer.connector")
    logger.info("connector_started operation=%s", args.operation)
    try:
        if args.operation != "candidate":
            if (
                args.local_only
                or execute_artifacts is None
                or args.start is not None
                or args.end is not None
                or args.prior is not None
                or args.fetch_workers is not None
            ):
                raise ConnectorConfigurationError("Invalid artifact operation")
            receipt = execute_artifacts(
                ConnectorArtifactInput(
                    args.operation,
                    args.staging,
                    args.manifest,
                    args.config,
                    args.s3_workers,
                )
            )
            print(f"{args.operation}_verified; no publication")
            print(f"manifest={receipt.manifest.sha256}:{receipt.manifest.byte_count}")
            print(f"objects={receipt.objects}; bytes={receipt.byte_count}")
            return 0
        if args.manifest is not None:
            raise ConnectorConfigurationError("Invalid candidate operation")
        inputs = ConnectorInput(
            args.start,
            args.end,
            args.staging,
            args.prior,
            args.config,
            args.fetch_workers,
            args.s3_workers,
        )
        durable_result = None
        if args.local_only:
            result = execute(inputs)
        else:
            if execute_durable is None:
                raise ConnectorConfigurationError("Missing durable connector executor")
            durable_result = execute_durable(inputs)
            result = durable_result.candidate
    except ConnectorConfigurationError:
        logger.error("connector_failed code=configuration")
        print("failed configuration; no publication")
        return 2
    except ConnectorDependencyError:
        logger.error("connector_failed code=aws_dependency")
        print(
            "failed aws_dependency; run make setup to install SDK login support; no publication"
        )
        return 1
    except KeyboardInterrupt:
        logger.error("connector_failed code=interrupted")
        print("failed interrupted; no publication")
        return 130
    except Exception:
        logger.error("connector_failed code=internal")
        print("failed internal; no publication")
        return 1
    report = result.report
    if durable_result is not None and durable_result.error is not None:
        print(
            f"failed persistence run={report.run_id}; local_candidate_verified=true; no publication"
        )
        print(f"error={durable_result.error}; report_written={result.report_written}")
        if durable_result.error == "aws_dependency":
            print("Run make setup to install AWS SDK login support.")
        if report.manifest is not None:
            print(
                f"local_manifest={report.manifest.sha256}:{report.manifest.byte_count}"
            )
        return (
            130
            if durable_result.error == "interrupted"
            else 2
            if durable_result.error == "configuration"
            else 1
        )
    if durable_result is not None and durable_result.receipt is not None:
        receipt = durable_result.receipt
        print(
            f"candidate_s3_verified run={report.run_id}; local_outcome={report.outcome}; no publication"
        )
        print(f"manifest={receipt.manifest.sha256}:{receipt.manifest.byte_count}")
        print(f"objects={receipt.objects}; bytes={receipt.byte_count}")
        return 0
    print(f"{report.outcome} run={report.run_id}; no publication")
    if report.error is not None:
        print(f"error={report.error}; report_written={result.report_written}")
    if report.manifest is not None:
        print(f"manifest={report.manifest.sha256}:{report.manifest.byte_count}")
    if report.error == "interrupted":
        return 130
    return 1 if report.outcome == "failed" else 0
