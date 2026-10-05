"""Reuse immutable local evidence and verify every pinned manifest dependency."""

import logging
from collections.abc import Iterable, Iterator
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    ExactArtifactStore,
    StoredObject,
)
from outage_explorer.application.ports.candidates import (
    CandidateManifest,
    EvidenceBundle,
    SanitizedPage,
)
from outage_explorer.application.ports.connector_workers import ConnectorWorkers
from outage_explorer.domain.refresh import RefreshBounds
from outage_explorer.infrastructure.parquet.candidates import ParquetCandidateBuilder
from outage_explorer.infrastructure.parquet.evidence import write_evidence
from outage_explorer.infrastructure.parquet.manifests import load_manifest
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore

_LOG = logging.getLogger("outage_explorer.connector.parquet")


class LocalConnectorEvidence:
    def __init__(
        self, store: LocalParquetStore, workers: ConnectorWorkers | None = None
    ) -> None:
        self.store, self.workers = store, workers

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
                refs.extend(bundle.transport)
            objects += len(refs)
            size += sum(item.byte_count for item in refs)
            if (
                objects > self.store.bounds.objects
                or size > self.store.bounds.total_bytes
            ):
                raise ArtifactLimitError("Manifest graph exceeds bounds")
            _LOG.info("manifest_replay_started sha256=%s", ref.sha256)
            builder.verify(current, bounds)
            _LOG.info("manifest_replay_verified sha256=%s", ref.sha256)
            if current.base_manifest_object is None:
                return result
            current = load_manifest(self.store, current.base_manifest_object)

    def read(self, reference: StoredObject) -> Iterator[bytes]:
        return self.store.read(reference)

    def graph(
        self, reference: StoredObject, bounds: RefreshBounds
    ) -> tuple[StoredObject, ...]:
        self.reopen(reference, bounds)
        refs: dict[str, StoredObject] = {}
        current = load_manifest(self.store, reference)
        while True:
            for item in manifest_dependencies(current):
                previous = refs.get(item.key)
                if previous is not None and previous != item:
                    raise ArtifactError("Conflicting graph dependency")
                refs[item.key] = item
            assert current.manifest_object is not None
            refs[current.manifest_object.key] = current.manifest_object
            if current.base_manifest_object is None:
                break
            current = load_manifest(self.store, current.base_manifest_object)
        # Dependencies (including ancestor manifests) precede the final manifest.
        refs.pop(reference.key)
        return (*refs.values(), reference)

    def restore(
        self, reference: StoredObject, source: ExactArtifactStore, bounds: RefreshBounds
    ) -> CandidateManifest:
        if any(self.store.root.iterdir()):
            raise ArtifactError("Recovery requires empty staging objects")
        pending = [reference]
        manifests: set[str] = set()
        downloaded: dict[str, StoredObject] = {}
        total = 0

        def transfer(ref: StoredObject) -> None:
            # Accounting/discovery are coordinator-owned; only exact object I/O
            # runs in workers. Local store commits share atomic aggregate caps.
            self.store._path(ref)
            _LOG.info(
                "graph_restore_object sha256=%s bytes=%d", ref.sha256, ref.byte_count
            )
            restored = self.store.put_immutable(source.read(ref))
            if restored != ref:
                raise ArtifactError("Restored artifact identity mismatch")

        def schedule(refs: Iterable[StoredObject]) -> None:
            nonlocal total
            tasks = []
            for ref in refs:
                previous = downloaded.get(ref.key)
                if previous is not None:
                    if previous != ref:
                        raise ArtifactError("Conflicting graph dependency")
                    continue
                self.store._path(ref)
                if len(downloaded) >= self.store.bounds.objects or (
                    total + ref.byte_count > self.store.bounds.total_bytes
                ):
                    raise ArtifactLimitError("Manifest graph exceeds bounds")
                downloaded[ref.key] = ref
                total += ref.byte_count
                tasks.append(partial(transfer, ref))
            if self.workers is None:
                for task in tasks:
                    task()
            else:
                self.workers.run(tasks)

        while pending:
            manifest_ref = pending.pop()
            if manifest_ref.key in manifests:
                raise ArtifactError("Invalid manifest ancestry")
            manifests.add(manifest_ref.key)
            schedule((manifest_ref,))
            manifest = load_manifest(self.store, manifest_ref)
            schedule(manifest_dependencies(manifest))
            if manifest.base_manifest_object is not None:
                pending.append(manifest.base_manifest_object)
        _LOG.info(
            "graph_restore_verification_started objects=%d bytes=%d",
            len(downloaded),
            total,
        )
        candidate = self.reopen(reference, bounds)
        if self.workers is not None:
            self.workers.run(())
        _LOG.info("graph_restore_verified objects=%d bytes=%d", len(downloaded), total)
        return candidate

    def verify_remote(
        self, reference: StoredObject, source: ExactArtifactStore, bounds: RefreshBounds
    ) -> None:
        with TemporaryDirectory(prefix="connector-readback-") as root:
            target = LocalParquetStore(
                Path(root) / "objects", self.store.bounds, self.store.check
            )
            LocalConnectorEvidence(target, self.workers).restore(
                reference, source, bounds
            )


def manifest_dependencies(manifest: CandidateManifest) -> tuple[StoredObject, ...]:
    """Explicit dependencies only; never enumerate a directory or bucket prefix."""
    refs = [
        item.object
        for item in (
            *manifest.modeled,
            *manifest.base_modeled,
            *manifest.dispositions,
            *manifest.ledger,
        )
    ]
    for bundle in (*manifest.evidence, *manifest.inherited_evidence):
        refs.extend(item.object for item in (*bundle.raw, *bundle.pages))
        refs.extend(bundle.transport)
    return tuple(refs)
