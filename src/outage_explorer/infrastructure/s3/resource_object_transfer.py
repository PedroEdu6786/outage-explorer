"""Conditional resource uploads and streamed S3 readback verification."""

import base64
import hashlib
import logging
import tempfile
from collections.abc import Iterable, Iterator
from typing import Any, BinaryIO, cast

from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
)

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    StoredObject,
    TransferBounds,
)
from outage_explorer.infrastructure.s3.transfer_budget import TransferBudget

_LOG = logging.getLogger("outage_explorer.connector.s3")
_PUT_RETRY_CODES = frozenset(
    {
        "ConditionalRequestConflict",
        "409",
        "SlowDown",
        "500",
        "503",
        "InternalError",
        "ServiceUnavailable",
        "RequestTimeout",
    }
)
_GET_RETRY_CODES = frozenset(
    {"SlowDown", "500", "503", "InternalError", "ServiceUnavailable"}
)


class ResourceObjectTransfer:
    """S3 byte exchange for resource objects admitted by S3ResourceStore."""

    def __init__(
        self, client: Any, bucket: str, transfer: TransferBounds, budget: TransferBudget
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.transfer = transfer
        self._budget = budget

    def upload_and_verify(
        self, reference: StoredObject, chunks: Iterable[bytes]
    ) -> None:
        # Bounded disk staging makes single PutObject replayable without retaining
        # a complete Parquet file in memory. Its cap also stays below S3's 5GB PUT.
        with (
            self._budget.staging(reference.byte_count),
            tempfile.TemporaryFile() as body,
        ):
            digest = self._stage_upload(reference, chunks, body)
            existing = self._put_conditional(reference, digest, body)
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

    def _stage_upload(
        self, reference: StoredObject, chunks: Iterable[bytes], body: BinaryIO
    ) -> bytes:
        digest, count = hashlib.sha256(), 0
        for chunk in chunks:
            self._budget.deadline()
            if not isinstance(chunk, bytes):
                raise ArtifactError("Artifact chunks must be bytes")
            count += len(chunk)
            if count > reference.byte_count:
                raise ArtifactError("Artifact upload byte count mismatch")
            digest.update(chunk)
            body.write(chunk)
        if count != reference.byte_count or digest.hexdigest() != reference.sha256:
            raise ArtifactError("Artifact upload checksum mismatch")
        return digest.digest()

    def _put_conditional(
        self, reference: StoredObject, digest: bytes, body: BinaryIO
    ) -> bool:
        for attempt in range(1, self.transfer.attempts + 1):
            self._budget.charge(reference.byte_count)
            body.seek(0)
            _LOG.info(
                "s3_create_attempt sha256=%s bytes=%d attempt=%d conditional=true",
                reference.sha256,
                reference.byte_count,
                attempt,
            )
            try:
                self._put_once(reference, digest, body)
                return False
            except ClientError as error:
                code = error.response.get("Error", {}).get("Code")
                if code in ("PreconditionFailed", "412"):
                    _LOG.info(
                        "s3_existing_object sha256=%s action=compare_bytes",
                        reference.sha256,
                    )
                    return True
                if code not in _PUT_RETRY_CODES or attempt == self.transfer.attempts:
                    raise ArtifactError("Artifact upload failed") from None
            except (BotoCoreError, OSError):
                if attempt == self.transfer.attempts:
                    raise ArtifactError("Artifact upload retries exhausted") from None
            _LOG.warning(
                "s3_create_retry sha256=%s attempt=%d",
                reference.sha256,
                attempt,
            )
        raise ArtifactError("Artifact upload retries exhausted")

    def _put_once(self, reference: StoredObject, digest: bytes, body: BinaryIO) -> None:
        self._budget.request()
        self.client.put_object(
            Bucket=self.bucket,
            Key=reference.key,
            Body=body,
            ContentLength=reference.byte_count,
            IfNoneMatch="*",
            ChecksumSHA256=base64.b64encode(digest).decode("ascii"),
        )

    def read(self, reference: StoredObject) -> Iterator[bytes]:
        response = self._get_with_retries(reference)
        body = response.get("Body")
        try:
            self._check_readback_length(response, reference)
            yield from self._verified_chunks(body, reference)
        except (BotoCoreError, OSError):
            raise ArtifactError("Artifact readback interrupted") from None
        finally:
            if body is not None:
                body.close()

    @staticmethod
    def _check_readback_length(
        response: dict[str, Any], reference: StoredObject
    ) -> None:
        if (
            type(response.get("ContentLength")) is int
            and response["ContentLength"] == reference.byte_count
            and response.get("Body") is not None
        ):
            return
        _LOG.error(
            "s3_readback_rejected sha256=%s reason=byte_count_mismatch action=abort_preserve_existing",
            reference.sha256,
        )
        raise ArtifactError("Artifact readback byte count mismatch")

    def _verified_chunks(self, body: Any, reference: StoredObject) -> Iterator[bytes]:
        digest, count = hashlib.sha256(), 0
        while True:
            self._budget.deadline()
            # Read one byte beyond the expected size so extra data is rejected.
            # Atomic charging also rejects races across concurrent readers.
            read_size = min(
                self.transfer.chunk_bytes,
                reference.byte_count - count + 1,
                self.transfer.wire_bytes + 1,
            )
            chunk = body.read(read_size)
            if not isinstance(chunk, bytes):
                raise ArtifactError("Invalid artifact readback")
            self._budget.charge(len(chunk))
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
        _LOG.info("s3_readback_verified sha256=%s bytes=%d", reference.sha256, count)

    def _get_with_retries(self, reference: StoredObject) -> dict[str, Any]:
        for attempt in range(self.transfer.attempts):
            self._budget.deadline()
            try:
                _LOG.info(
                    "s3_readback_started sha256=%s bytes=%d attempt=%d",
                    reference.sha256,
                    reference.byte_count,
                    attempt + 1,
                )
                self._budget.request()
                return cast(
                    dict[str, Any],
                    self.client.get_object(Bucket=self.bucket, Key=reference.key),
                )
            except ClientError as error:
                code = error.response.get("Error", {}).get("Code")
                if (
                    code not in _GET_RETRY_CODES
                    or attempt + 1 == self.transfer.attempts
                ):
                    raise ArtifactError("Artifact readback unavailable") from None
            except (BotoCoreError, OSError):
                if attempt + 1 == self.transfer.attempts:
                    raise ArtifactError("Artifact readback retries exhausted") from None
            _LOG.warning(
                "s3_readback_retry sha256=%s attempt=%d", reference.sha256, attempt + 1
            )
        raise ArtifactError("Artifact readback unavailable")

    def verify(self, reference: StoredObject) -> None:
        for _ in self.read(reference):
            pass
