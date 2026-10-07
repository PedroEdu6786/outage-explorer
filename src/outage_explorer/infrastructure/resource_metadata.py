"""Bounded local transport for exact resource identities; never stored in S3."""

import json
import os
import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    GrainSummary,
    validate_resources,
)
from outage_explorer.application.ports.connector import DurableResourceReceipt
from outage_explorer.domain.observations import Reason
from outage_explorer.domain.refresh import Interval, Quality

LIMIT = 65536


def _read(path: str) -> dict[str, Any]:
    try:
        with Path(path).open("rb") as source:
            payload = source.read(LIMIT + 1)
        if len(payload) > LIMIT:
            raise ValueError

        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        value = json.loads(payload, object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, ValueError, RecursionError):
        raise ArtifactError("Invalid local resource metadata") from None


def _identity(value: dict[str, Any]) -> dict[str, Any]:
    interval = value["interval"]
    resources = tuple(
        ArtifactRef(
            StoredObject(**item["object"]),
            item["kind"],
            item["grain"],
            item["partition"],
            item["row_count"],
            item["schema_version"],
        )
        for item in value["resources"]
    )
    validate_resources(resources)
    return dict(
        generation_id=value["generation_id"],
        resources=resources,
        interval=Interval(
            date.fromisoformat(interval["start"]), date.fromisoformat(interval["end"])
        ),
        contract_id=value["contract_id"],
        transformation_id=value["transformation_id"],
        base_generation_id=value["base_generation_id"],
        schema_version=value["schema_version"],
    )


def read_candidate(path: str) -> CandidateResult:
    try:
        value = _read(path)
        # Candidate identity is the bounded local report's final payload.
        value = value["candidate"] if "candidate" in value else value
        summaries = []
        for summary in value["summaries"]:
            quality = summary["quality"]
            quality["reason_counts"] = tuple(
                (Reason(**reason), count) for reason, count in quality["reason_counts"]
            )
            summaries.append(
                GrainSummary(
                    **(
                        summary
                        | {
                            "quality": Quality(**quality),
                            "first_period": None
                            if summary["first_period"] is None
                            else date.fromisoformat(summary["first_period"]),
                            "last_period": None
                            if summary["last_period"] is None
                            else date.fromisoformat(summary["last_period"]),
                        }
                    )
                )
            )
        return CandidateResult(
            **_identity(value), summaries=tuple(summaries), outcome=value["outcome"]
        )
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ArtifactError("Invalid local candidate identity") from None


def read_receipt(path: str) -> DurableResourceReceipt:
    try:
        return DurableResourceReceipt(**_identity(_read(path)))
    except (KeyError, TypeError, ValueError, RecursionError):
        raise ArtifactError("Invalid durable resource identity") from None


def write_receipt(path: Path, receipt: DurableResourceReceipt) -> None:
    payload = json.dumps(
        asdict(receipt),
        default=lambda value: value.isoformat(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if len(payload) > LIMIT:
        raise ArtifactError("Local resource identity exceeds bound")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".receipt-", delete=False
        ) as target:
            temporary = Path(target.name)
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
