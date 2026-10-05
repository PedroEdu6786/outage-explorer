"""Versioned JSON manifests name immutable objects, never directory listings."""

import json
from dataclasses import asdict, replace
from datetime import date
from typing import Any

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.application.ports.candidates import (
    CandidateManifest,
    EvidenceBundle,
    GrainSummary,
)
from outage_explorer.domain.observations import IDENTITY_FIELDS, Reason
from outage_explorer.domain.refresh import Interval, Quality
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


def validate_manifest(manifest: CandidateManifest) -> None:
    """Reject JSON booleans/coercions that compare equal to valid integer counts."""

    def integer(value: object, minimum: int = 0) -> None:
        if type(value) is not int or value < minimum:
            raise ArtifactError("Manifest counts must be exact nonnegative integers")

    def identifier(value: object) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ArtifactError("Invalid manifest identity")

    for value in (
        manifest.generation_id,
        manifest.contract_id,
        manifest.transformation_id,
    ):
        identifier(value)
    if manifest.base_generation_id is not None:
        identifier(manifest.base_generation_id)
    if manifest.schema_version != "1" or manifest.outcome not in (
        "candidate",
        "retained_all_excluded",
    ):
        raise ArtifactError("Unsupported manifest version or outcome")
    for summary in manifest.summaries:
        if summary.grain not in IDENTITY_FIELDS:
            raise ArtifactError("Invalid summary grain")
        for name, value in vars(summary).items():
            if name not in ("grain", "quality"):
                integer(value)
        for name, value in vars(summary.quality).items():
            if name != "reason_counts":
                integer(value)
        for reason, count in summary.quality.reason_counts:
            identifier(reason.field)
            identifier(reason.code)
            integer(count, 1)
    refs = [
        *manifest.modeled,
        *manifest.base_modeled,
        *manifest.dispositions,
        *manifest.ledger,
    ]
    for bundle in (*manifest.evidence, *manifest.inherited_evidence):
        if bundle.grain not in IDENTITY_FIELDS:
            raise ArtifactError("Invalid evidence grain")
        refs.extend((*bundle.raw, *bundle.pages))
        for supplemental in bundle.transport:
            integer(supplemental.byte_count, 1)
            identifier(supplemental.key)
            identifier(supplemental.sha256)
    for ref in refs:
        if (
            ref.grain not in IDENTITY_FIELDS
            or ref.kind not in ("raw", "pages", "modeled", "dispositions", "ledger")
            or ref.schema_version != "1"
        ):
            raise ArtifactError("Invalid artifact descriptor")
        integer(ref.row_count, 1)
        integer(ref.object.byte_count, 1)
        identifier(ref.object.key)
        identifier(ref.object.sha256)
    for ref_object in (manifest.manifest_object, manifest.base_manifest_object):
        if ref_object is not None:
            integer(ref_object.byte_count, 1)
            identifier(ref_object.key)
            identifier(ref_object.sha256)


def manifest_bytes(manifest: CandidateManifest) -> bytes:
    validate_manifest(manifest)
    value = asdict(replace(manifest, manifest_object=None))
    # Preserve byte-for-byte canonical legacy manifests when the extension is absent.
    for name in ("evidence", "inherited_evidence"):
        for bundle in value[name]:
            if not bundle["transport"]:
                bundle.pop("transport")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=_date
    ).encode()


def _date(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError("Unsupported manifest value")


def persist_manifest(
    store: LocalParquetStore, manifest: CandidateManifest
) -> CandidateManifest:
    payload = manifest_bytes(manifest)
    if len(payload) > store.bounds.file_bytes:
        raise ArtifactLimitError("Manifest byte bound exceeded")
    reference = store.put_immutable((payload,))
    return replace(manifest, manifest_object=reference)


def _interval(value: dict[str, Any]) -> Interval:
    return Interval(
        date.fromisoformat(value["start"]), date.fromisoformat(value["end"])
    )


def _ref(value: dict[str, Any]) -> ArtifactRef:
    return ArtifactRef(
        StoredObject(**value["object"]),
        value["kind"],
        value["grain"],
        date.fromisoformat(value["partition"]) if value["partition"] else None,
        value["row_count"],
        value["schema_version"],
    )


def _bundle(value: dict[str, Any]) -> EvidenceBundle:
    return EvidenceBundle(
        value["grain"],
        _interval(value["interval"]),
        tuple(_ref(ref) for ref in value["raw"]),
        tuple(_ref(ref) for ref in value["pages"]),
        tuple(StoredObject(**ref) for ref in value.get("transport", [])),
    )


def load_manifest(
    store: LocalParquetStore, reference: StoredObject
) -> CandidateManifest:
    if reference.byte_count > store.bounds.file_bytes:
        raise ArtifactLimitError("Manifest byte bound exceeded")
    payload = b"".join(store.read(reference))
    try:
        value = json.loads(payload)
        summaries = []
        for summary in value["summaries"]:
            quality = summary["quality"]
            quality["reason_counts"] = tuple(
                (Reason(**reason), count) for reason, count in quality["reason_counts"]
            )
            summaries.append(GrainSummary(**{**summary, "quality": Quality(**quality)}))
        manifest = CandidateManifest(
            generation_id=value["generation_id"],
            base_generation_id=value["base_generation_id"],
            interval=_interval(value["interval"]),
            evidence=tuple(_bundle(item) for item in value["evidence"]),
            inherited_evidence=tuple(
                _bundle(item) for item in value["inherited_evidence"]
            ),
            base_modeled=tuple(_ref(item) for item in value["base_modeled"]),
            modeled=tuple(_ref(item) for item in value["modeled"]),
            dispositions=tuple(_ref(item) for item in value["dispositions"]),
            ledger=tuple(_ref(item) for item in value["ledger"]),
            summaries=tuple(summaries),
            outcome=value["outcome"],
            contract_id=value["contract_id"],
            transformation_id=value["transformation_id"],
            schema_version=value["schema_version"],
            manifest_object=reference,
            base_manifest_object=(
                StoredObject(**value["base_manifest_object"])
                if value["base_manifest_object"]
                else None
            ),
        )
        if manifest.schema_version != "1" or manifest_bytes(manifest) != payload:
            raise ArtifactError("Unsupported or noncanonical manifest")
        return manifest
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ArtifactError("Invalid candidate manifest") from error
