"""Exact generation-scoped three-resource transfers; no manifest discovery."""

import re
from collections.abc import Iterable
from contextlib import AbstractContextManager
from dataclasses import replace

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.application.ports.candidates import validate_resources
from outage_explorer.application.ports.connector import DurableResourceReceipt
from outage_explorer.infrastructure.s3.artifacts import S3ArtifactStore

_FILES = {
    "national": "national.parquet",
    "facility": "facilities.parquet",
    "generator": "generators.parquet",
}


class S3ResourceStore(S3ArtifactStore):
    """Reuse conditional PUT/full GET and shared session limits with exact keys."""

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
            self._key(remote.object)
        return refs

    def validate_receipt(self, receipt: DurableResourceReceipt) -> None:
        validate_resources(receipt.resources)
        prefix = self._generation_prefix(receipt.generation_id)
        for ref in receipt.resources:
            if ref.object.key != prefix + _FILES[ref.grain]:
                raise ArtifactError("Resource receipt address mismatch")
        for ref in receipt.resources:
            self._key(ref.object)

    def _key(self, reference: StoredObject) -> str:
        self._deadline()
        suffix = reference.key.removeprefix(self.prefix + "generations/")
        parts = suffix.split("/")
        if (
            len(parts) != 2
            or parts[1] not in _FILES.values()
            or reference.key != self._generation_prefix(parts[0]) + parts[1]
            or not re.fullmatch(r"[0-9a-f]{64}", reference.sha256)
        ):
            raise ArtifactError("Invalid exact resource address")
        self._register(reference)
        return reference.key

    def put_verified(
        self, reference: ArtifactRef, chunks: Iterable[bytes]
    ) -> ArtifactRef:
        if (
            reference.kind != "resource"
            or reference.partition is not None
            or reference.schema_version != "1"
        ):
            raise ArtifactError("Invalid resource descriptor")
        if reference.object.key.rsplit("/", 1)[-1] != _FILES.get(reference.grain):
            raise ArtifactError("Resource grain/address mismatch")
        self.put_exact(reference.object, chunks)
        return reference

    def recovery_staging(self, size: int) -> AbstractContextManager[None]:
        """Hold the shared reservation until restored files validate or clean up."""
        return self._staging(size)

    def reference(self, key: str, digest: str) -> StoredObject:
        raise ArtifactError("Resource recovery requires complete exact descriptors")
