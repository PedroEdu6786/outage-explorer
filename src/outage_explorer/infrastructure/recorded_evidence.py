"""Local, checksum-verified evidence. Never retrieves source data."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import cast

from outage_explorer.application.dto import EvidenceArtifact, EvidenceBundle
from outage_explorer.application.errors import VerificationError
from outage_explorer.domain.observations import Grain, SourceRecord


class LocalRecordedEvidence:
    """Load a local manifest and its verified, immutable source records."""

    def __init__(self, grain: Grain = "national") -> None:
        self._grain = grain

    def load(self, bundle_reference: str) -> EvidenceBundle:
        try:
            return self._load_bundle(Path(bundle_reference).resolve())
        except (OSError, ValueError, UnicodeError) as error:
            raise VerificationError(f"Cannot read evidence: {error}") from error

    def _load_bundle(self, manifest_path: Path) -> EvidenceBundle:
        manifest_bytes = manifest_path.read_bytes()
        manifest = _parse_json_object(manifest_bytes)
        _validate_manifest(manifest, self._grain)

        expected_checksums = cast(dict[str, object], manifest["artifacts"])
        artifacts = {
            name: _read_verified_artifact(manifest_path, name, digest)
            for name, digest in sorted(expected_checksums.items())
        }
        snapshot_name = cast(str, manifest["snapshot"])
        records = _read_snapshot_records(artifacts[snapshot_name].document, manifest)
        response = cast(
            dict[str, object], artifacts[snapshot_name].document["response"]
        )
        total = response.get("total")
        if not isinstance(total, str) or not total.isascii() or not total.isdigit():
            raise VerificationError(
                "Response total must be a nonnegative integer string"
            )

        return EvidenceBundle(
            manifest_json=manifest_bytes.decode("utf-8"),
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            artifacts=tuple(artifact.identity for artifact in artifacts.values()),
            records=records,
            protected_paths=(
                str(manifest_path),
                *(str(artifact.path) for artifact in artifacts.values()),
            ),
            response_total=total,
        )


@dataclass(frozen=True)
class _VerifiedArtifact:
    identity: EvidenceArtifact
    path: Path
    document: dict[str, object]


def _validate_manifest(manifest: dict[str, object], grain: Grain) -> None:
    for version in ("bundle_version", "contract_version", "report_version"):
        if type(manifest.get(version)) is not int or manifest[version] != 1:
            raise VerificationError(f"Unsupported {version}")
    if manifest.get("start") != "2026-09-01" or manifest.get("end") != "2026-09-30":
        raise VerificationError("Evidence must use the fixed September 2026 interval")
    for name in ("bundle_id", "source_url", "retrieved_at_utc", "snapshot"):
        if not isinstance(manifest.get(name), str) or not manifest[name]:
            raise VerificationError(f"Missing manifest identity: {name}")
    if manifest.get("evidence_kind") not in ("recorded", "synthetic"):
        raise VerificationError("Evidence must be identified as recorded or synthetic")
    route = "us" if grain == "national" else grain
    expected_url = (
        f"https://api.eia.gov/v2/nuclear-outages/{route}-nuclear-outages/data/"
    )
    if (
        manifest.get("source_url") != expected_url
        or manifest.get("dataset", "national") != grain
    ):
        raise VerificationError(f"Evidence dataset does not match {grain} verifier")

    _validate_request_parameters(manifest.get("parameters"))

    required_artifacts = {
        "metadata.json",
        "profile.json",
        "capacity-semantics.json",
        cast(str, manifest["snapshot"]),
    }
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not required_artifacts <= artifacts.keys():
        raise VerificationError("Incomplete evidence artifact references")


def _validate_request_parameters(parameters: object) -> None:
    if not isinstance(parameters, dict):
        raise VerificationError("Missing recorded request parameters")
    expected_parameters = {
        "start": "2026-09-01",
        "end": "2026-09-30",
        "frequency": "daily",
    }
    if any(
        parameters.get(name) != expected
        for name, expected in expected_parameters.items()
    ):
        raise VerificationError(
            "Recorded request does not identify the fixed daily baseline"
        )


def _read_verified_artifact(
    manifest_path: Path, name: str, expected_sha256: object
) -> _VerifiedArtifact:
    base = manifest_path.parent
    path = (base / name).resolve()
    if (
        Path(name).is_absolute()
        or not path.is_relative_to(base)
        or path == manifest_path
    ):
        raise VerificationError("Artifact paths must stay inside the evidence bundle")

    content = path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise VerificationError(f"Evidence checksum mismatch: {name}")

    return _VerifiedArtifact(
        identity=EvidenceArtifact(name=name, sha256=actual_sha256),
        path=path,
        document=_parse_json_object(content),
    )


def _read_snapshot_records(
    snapshot: dict[str, object], manifest: dict[str, object]
) -> tuple[SourceRecord, ...]:
    for name in ("source_url", "parameters", "retrieved_at_utc"):
        if snapshot.get(name) != manifest[name]:
            raise VerificationError(
                f"Snapshot provenance differs from manifest: {name}"
            )

    response = snapshot.get("response")
    if not isinstance(response, Mapping) or not isinstance(response.get("data"), list):
        raise VerificationError("Expected response.data array in recorded evidence")
    if (
        response.get("frequency") != "daily"
        or response.get("dateFormat") != "YYYY-MM-DD"
    ):
        raise VerificationError("Unsupported daily response envelope")

    # Preserve every row and its source position; domain policies assess usability.
    return tuple(
        SourceRecord(position=index, value=_freeze_json(row))
        for index, row in enumerate(response["data"])
    )


def _parse_json_object(content: bytes) -> dict[str, object]:
    value = json.loads(
        content,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_json_constant,
    )
    if not isinstance(value, dict):
        raise VerificationError("Evidence document must be a JSON object")
    return cast(dict[str, object], value)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> object:
    raise VerificationError(f"Non-JSON numeric constant: {value}")


def _freeze_json(value: object) -> object:
    """Keep nested source evidence immutable without coercing its scalar values."""
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value
