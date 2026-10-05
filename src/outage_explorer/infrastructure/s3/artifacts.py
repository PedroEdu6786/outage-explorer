"""Conditional S3 creation and bounded, SHA-256 verified streamed readback."""

import base64
import hashlib
import logging
import re
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from threading import Event, RLock
from typing import Any

from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
)

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
    StoredObject,
    TransferBounds,
)

_LOG = logging.getLogger("outage_explorer.connector.s3")


class S3ArtifactStore:
    """A transfer session. Inject a configured SDK client, never caller URLs.

    SDK internal retries must be disabled by composition. Logical object keys
    match local content identities; physical keys are generated under the prefix.
    No listing, mutation, delete or multipart operation is exposed.
    """

    def __init__(
        self,
        client: Any,
        bucket: str,
        prefix: str,
        bounds: ArtifactBounds,
        transfer: TransferBounds | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        cancelled: Event | None = None,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) or (
            not prefix
            or not re.fullmatch(r"[A-Za-z0-9_/-]+/", prefix)
            or any(part in (".", "..", "") for part in prefix[:-1].split("/"))
        ):
            raise ValueError("Invalid artifact storage configuration")
        self.client, self.bucket, self.prefix = client, bucket, prefix
        self.bounds, self.transfer, self.monotonic = (
            bounds,
            TransferBounds() if transfer is None else transfer,
            monotonic,
        )
        self.cancelled = Event() if cancelled is None else cancelled
        self.lock = RLock()
        self.requests = self.temporary_bytes = 0
        self.started = monotonic()
        self.wire_bytes = 0
        self.objects: dict[str, StoredObject] = {}

    def _deadline(self) -> None:
        if (
            self.cancelled.is_set()
            or self.monotonic() - self.started >= self.transfer.elapsed_seconds
        ):
            raise ArtifactLimitError("Artifact transfer deadline exhausted")

    def _key(self, reference: StoredObject) -> str:
        self._deadline()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", reference.key)
            or reference.sha256 != reference.key
        ):
            raise ArtifactError("Invalid exact artifact identity")
        if type(reference.byte_count) is not int or not (
            0 < reference.byte_count <= min(self.bounds.file_bytes, 5_000_000_000)
        ):
            raise ArtifactLimitError("Artifact file bound exceeded")
        with self.lock:
            previous = self.objects.get(reference.key)
            if previous is not None and previous != reference:
                raise ArtifactError("Conflicting exact artifact reference")
            if previous is None:
                if len(self.objects) >= self.bounds.objects or (
                    sum(item.byte_count for item in self.objects.values())
                    + reference.byte_count
                    > self.bounds.total_bytes
                ):
                    raise ArtifactLimitError("Artifact graph bound exceeded")
                self.objects[reference.key] = reference
        return self.prefix + "objects/" + reference.key

    def _charge(self, size: int) -> None:
        with self.lock:
            self._deadline()
            if self.wire_bytes + size > self.transfer.wire_bytes:
                self.cancelled.set()
                raise ArtifactLimitError("Artifact transfer byte bound exceeded")
            self.wire_bytes += size

    def _request(self) -> None:
        with self.lock:
            self._deadline()
            if self.requests >= self.transfer.requests:
                self.cancelled.set()
                raise ArtifactLimitError("Artifact transfer request bound exceeded")
            self.requests += 1

    @contextmanager
    def _staging(self, size: int) -> Iterator[None]:
        with self.lock:
            self._deadline()
            if self.temporary_bytes + size > self.transfer.temporary_bytes:
                self.cancelled.set()
                raise ArtifactLimitError("Aggregate temporary disk bound exceeded")
            self.temporary_bytes += size
        try:
            yield
        finally:
            with self.lock:
                self.temporary_bytes -= size

    def put_exact(self, reference: StoredObject, chunks: Iterable[bytes]) -> None:
        key = self._key(reference)
        # Bounded disk staging makes single PutObject replayable without retaining
        # a complete Parquet file in memory. Its cap also stays below S3's 5GB PUT.
        with self._staging(reference.byte_count), tempfile.TemporaryFile() as body:
            digest, count = hashlib.sha256(), 0
            for chunk in chunks:
                self._deadline()
                if not isinstance(chunk, bytes):
                    raise ArtifactError("Artifact chunks must be bytes")
                count += len(chunk)
                if count > reference.byte_count:
                    raise ArtifactError("Artifact upload byte count mismatch")
                digest.update(chunk)
                body.write(chunk)
            if count != reference.byte_count or digest.hexdigest() != reference.sha256:
                raise ArtifactError("Artifact upload checksum mismatch")
            existing = False
            for attempt in range(self.transfer.attempts):
                self._charge(count)
                body.seek(0)
                _LOG.info(
                    "s3_create_attempt sha256=%s bytes=%d attempt=%d conditional=true",
                    reference.sha256,
                    count,
                    attempt + 1,
                )
                try:
                    self._request()
                    self.client.put_object(
                        Bucket=self.bucket,
                        Key=key,
                        Body=body,
                        ContentLength=count,
                        IfNoneMatch="*",
                        ChecksumSHA256=base64.b64encode(digest.digest()).decode(
                            "ascii"
                        ),
                    )
                    break
                except ClientError as error:
                    code = error.response.get("Error", {}).get("Code")
                    if code in ("PreconditionFailed", "412"):
                        existing = True
                        _LOG.info(
                            "s3_existing_object sha256=%s action=compare_bytes",
                            reference.sha256,
                        )
                        break  # Existing bytes still require full verification.
                    if (
                        code
                        not in (
                            "ConditionalRequestConflict",
                            "409",
                            "SlowDown",
                            "500",
                            "503",
                            "InternalError",
                            "ServiceUnavailable",
                            "RequestTimeout",
                        )
                        or attempt + 1 == self.transfer.attempts
                    ):
                        raise ArtifactError("Artifact upload failed") from None
                except (BotoCoreError, OSError):
                    if attempt + 1 == self.transfer.attempts:
                        raise ArtifactError(
                            "Artifact upload retries exhausted"
                        ) from None
                _LOG.warning(
                    "s3_create_retry sha256=%s attempt=%d",
                    reference.sha256,
                    attempt + 1,
                )
            self.verify(reference)
            if existing:
                _LOG.info(
                    "s3_upload_skipped sha256=%s reason=identical_existing_bytes",
                    reference.sha256,
                )
            _LOG.info(
                "s3_object_verified sha256=%s bytes=%d",
                reference.sha256,
                reference.byte_count,
            )

    def read(self, reference: StoredObject) -> Iterator[bytes]:
        key = self._key(reference)
        response = None
        for attempt in range(self.transfer.attempts):
            self._deadline()
            try:
                _LOG.info(
                    "s3_readback_started sha256=%s bytes=%d attempt=%d",
                    reference.sha256,
                    reference.byte_count,
                    attempt + 1,
                )
                self._request()
                response = self.client.get_object(Bucket=self.bucket, Key=key)
                break
            except ClientError as error:
                code = error.response.get("Error", {}).get("Code")
                if (
                    code
                    not in (
                        "SlowDown",
                        "500",
                        "503",
                        "InternalError",
                        "ServiceUnavailable",
                    )
                    or attempt + 1 == self.transfer.attempts
                ):
                    raise ArtifactError("Artifact readback unavailable") from None
            except (BotoCoreError, OSError):
                if attempt + 1 == self.transfer.attempts:
                    raise ArtifactError("Artifact readback retries exhausted") from None
            _LOG.warning(
                "s3_readback_retry sha256=%s attempt=%d", reference.sha256, attempt + 1
            )
        if response is None:
            raise ArtifactError("Artifact readback unavailable")
        body = response.get("Body")
        try:
            if (
                type(response.get("ContentLength")) is not int
                or response["ContentLength"] != reference.byte_count
                or body is None
            ):
                _LOG.error(
                    "s3_readback_rejected sha256=%s reason=byte_count_mismatch action=abort_preserve_existing",
                    reference.sha256,
                )
                raise ArtifactError("Artifact readback byte count mismatch")
            digest, count = hashlib.sha256(), 0
            while True:
                self._deadline()
                chunk = body.read(
                    min(
                        self.transfer.chunk_bytes,
                        reference.byte_count - count + 1,
                        # Atomic charging below rejects races across readers.
                        self.transfer.wire_bytes + 1,
                    )
                )
                if not isinstance(chunk, bytes):
                    raise ArtifactError("Invalid artifact readback")
                self._charge(len(chunk))
                if not chunk:
                    break
                count += len(chunk)
                if count > reference.byte_count:
                    raise ArtifactError("Artifact readback byte count mismatch")
                digest.update(chunk)
                yield chunk
            if count != reference.byte_count or digest.hexdigest() != reference.sha256:
                _LOG.error(
                    "s3_readback_rejected sha256=%s reason=checksum_mismatch action=abort_preserve_existing",
                    reference.sha256,
                )
                raise ArtifactError("Artifact readback checksum mismatch")
            _LOG.info(
                "s3_readback_verified sha256=%s bytes=%d", reference.sha256, count
            )
        except (BotoCoreError, OSError):
            raise ArtifactError("Artifact readback interrupted") from None
        finally:
            if body is not None:
                body.close()

    def verify(self, reference: StoredObject) -> None:
        for _ in self.read(reference):
            pass
