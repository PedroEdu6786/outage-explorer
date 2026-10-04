"""Reuse immutable local evidence and verify every pinned manifest dependency."""

from collections.abc import Iterable

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    StoredObject,
)
from outage_explorer.application.ports.candidates import (
    CandidateManifest,
    EvidenceBundle,
    SanitizedPage,
)
from outage_explorer.domain.refresh import RefreshBounds
from outage_explorer.infrastructure.parquet.candidates import ParquetCandidateBuilder
from outage_explorer.infrastructure.parquet.evidence import write_evidence
from outage_explorer.infrastructure.parquet.manifests import load_manifest
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


class LocalConnectorEvidence:
    def __init__(self, store: LocalParquetStore) -> None:
        self.store = store

    def write(self, pages: Iterable[SanitizedPage]) -> EvidenceBundle:
        return write_evidence(self.store, pages)

    def reopen(
        self, reference: StoredObject, bounds: RefreshBounds
    ) -> CandidateManifest:
        # Iterative ancestor walk: no recursion or mutable active pointer. The
        # total graph scan (including repeated references) has an explicit cap.
        result = load_manifest(self.store, reference)
        current = result
        seen: set[str] = set()
        objects = size = 0
        builder = ParquetCandidateBuilder(self.store)
        while True:
            ref = current.manifest_object
            if ref is None or ref.key in seen:
                raise ArtifactError("Invalid manifest ancestry")
            seen.add(ref.key)
            refs = [
                ref,
                *(
                    item.object
                    for item in (
                        *current.modeled,
                        *current.base_modeled,
                        *current.dispositions,
                        *current.ledger,
                    )
                ),
            ]
            for bundle in (*current.evidence, *current.inherited_evidence):
                refs.extend(item.object for item in (*bundle.raw, *bundle.pages))
            objects += len(refs)
            size += sum(item.byte_count for item in refs)
            if (
                objects > self.store.bounds.objects
                or size > self.store.bounds.total_bytes
            ):
                raise ArtifactLimitError("Manifest graph exceeds bounds")
            builder.verify(current, bounds)
            if current.base_manifest_object is None:
                return result
            current = load_manifest(self.store, current.base_manifest_object)
