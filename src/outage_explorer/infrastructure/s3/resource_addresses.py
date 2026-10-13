"""Validate the three exact generation-scoped S3 resource addresses."""

import re
from dataclasses import replace

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.application.ports.candidates import validate_resources
from outage_explorer.application.ports.connector import DurableResourceReceipt

_FILES = {
    "national": "national.parquet",
    "facility": "facilities.parquet",
    "generator": "generators.parquet",
}


class ResourceAddresses:
    def __init__(self, bucket: str, prefix: str) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) or (
            not prefix
            or not re.fullmatch(r"[A-Za-z0-9_/-]+/", prefix)
            or any(part in (".", "..", "") for part in prefix[:-1].split("/"))
        ):
            raise ValueError("Invalid artifact storage configuration")
        self.prefix = prefix

    def _generation_prefix(self, generation_id: str) -> str:
        if not isinstance(generation_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]+", generation_id
        ):
            raise ArtifactError("Invalid resource generation identity")
        prefix = self.prefix + "generations/" + generation_id + "/"
        if len((prefix + "generators.parquet").encode("utf-8")) > 1024:
            raise ArtifactError("Resource address exceeds S3 key length")
        return prefix

    def addresses(
        self, generation_id: str, resources: tuple[ArtifactRef, ...]
    ) -> tuple[ArtifactRef, ...]:
        validate_resources(resources)
        prefix = self._generation_prefix(generation_id)
        refs = tuple(
            replace(ref, object=replace(ref.object, key=prefix + _FILES[ref.grain]))
            for ref in resources
        )
        for local, remote in zip(resources, refs, strict=True):
            if local.object.key != local.object.sha256:
                raise ArtifactError("Invalid logical resource identity")
            self.key(remote.object)
        return refs

    def validate_receipt(self, receipt: DurableResourceReceipt) -> None:
        validate_resources(receipt.resources)
        prefix = self._generation_prefix(receipt.generation_id)
        for ref in receipt.resources:
            if ref.object.key != prefix + _FILES[ref.grain]:
                raise ArtifactError("Resource receipt address mismatch")
        for ref in receipt.resources:
            self.key(ref.object)

    def validate_upload(self, reference: ArtifactRef) -> None:
        if (
            reference.kind != "resource"
            or reference.partition is not None
            or reference.schema_version != "1"
        ):
            raise ArtifactError("Invalid resource descriptor")
        if not isinstance(reference.object.key, str) or reference.object.key.rsplit(
            "/", 1
        )[-1] != _FILES.get(reference.grain):
            raise ArtifactError("Resource grain/address mismatch")
        self.key(reference.object)

    def key(self, reference: StoredObject) -> str:
        if not isinstance(reference.key, str):
            raise ArtifactError("Invalid exact resource address")
        suffix = reference.key.removeprefix(self.prefix + "generations/")
        parts = suffix.split("/")
        if (
            len(parts) != 2
            or parts[1] not in _FILES.values()
            or reference.key != self._generation_prefix(parts[0]) + parts[1]
            or not isinstance(reference.sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", reference.sha256)
        ):
            raise ArtifactError("Invalid exact resource address")
        return reference.key
