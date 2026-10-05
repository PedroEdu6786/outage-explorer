"""Controlled Boto3 client/StreamingBody evidence; never configured AWS calls."""

import base64
import hashlib
import io
import logging
from dataclasses import replace
from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.response import StreamingBody
from botocore.stub import Stubber

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    StoredObject,
    TransferBounds,
)
from outage_explorer.infrastructure.s3.artifacts import S3ArtifactStore
from tests.integration.test_connector_cli import ARTIFACT

SECRET = "synthetic-sdk-secret"


def reference(data=b"immutable bytes"):
    digest = hashlib.sha256(data).hexdigest()
    return StoredObject(digest, digest, len(data))


def failure(code):
    return ClientError({"Error": {"Code": code, "Message": SECRET}}, "PutObject")


class ControlledS3:
    """SDK-shaped fault transport; method surface forbids listing/deletion."""

    def __init__(self):
        self.objects = {}
        self.calls = []
        self.put_faults = []
        self.get_faults = []
        self.read_transform = None
        self.length_transform = None
        self.closed_bodies = []

    def put_object(self, **kwargs):
        assert kwargs["IfNoneMatch"] == "*"
        key = kwargs["Key"]
        data = kwargs["Body"].read()
        assert len(data) == kwargs["ContentLength"]
        assert (
            kwargs["ChecksumSHA256"]
            == base64.b64encode(hashlib.sha256(data).digest()).decode()
        )
        self.calls.append(("put", key))
        if self.put_faults:
            fault = self.put_faults.pop(0)
            if callable(fault):
                return fault(key, data)
            raise fault
        if key in self.objects:
            raise failure("PreconditionFailed")
        self.objects[key] = data
        return {"ETag": "deliberately-not-a-content-hash"}

    def get_object(self, **kwargs):
        key = kwargs["Key"]
        self.calls.append(("get", key))
        if self.get_faults:
            raise self.get_faults.pop(0)
        if key not in self.objects:
            raise failure("NoSuchKey")
        data = self.objects[key]
        value = self.read_transform(key, data) if self.read_transform else data
        length = (
            self.length_transform(key, data) if self.length_transform else len(data)
        )
        stream = io.BytesIO(value)
        self.closed_bodies.append(stream)
        return {
            "ContentLength": length,
            "Body": StreamingBody(stream, len(value)),
            "ETag": SECRET,
        }


def adapter(client=None, **kwargs):
    return S3ArtifactStore(
        ControlledS3() if client is None else client,
        "test-bucket",
        "connector/",
        ARTIFACT,
        **kwargs,
    )


def test_real_sdk_stubber_validates_conditional_parameters_and_readback():
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="synthetic",
        aws_secret_access_key="synthetic",
    )
    data = b"immutable bytes"
    ref = reference(data)
    with Stubber(client) as stub:
        from botocore.stub import ANY

        expected = {
            "Bucket": "test-bucket",
            "Key": "connector/objects/" + ref.key,
            "Body": ANY,
            "ContentLength": len(data),
            "IfNoneMatch": "*",
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(data).digest()).decode(),
        }
        stub.add_response("put_object", {"ETag": "untrusted-etag"}, expected)
        stub.add_response(
            "get_object",
            {
                "ContentLength": len(data),
                "Body": StreamingBody(io.BytesIO(data), len(data)),
            },
            {"Bucket": "test-bucket", "Key": expected["Key"]},
        )
        adapter(client).put_exact(ref, [data])
        stub.assert_no_pending_responses()
    client.close()


def test_conditional_retry_accepts_only_verified_identical_bytes():
    client = ControlledS3()
    ref, data = reference(), b"immutable bytes"
    adapter(client).put_exact(ref, [data])
    adapter(client).put_exact(ref, [data])
    assert len(client.objects) == 1
    assert all(stream.closed for stream in client.closed_bodies)
    client.objects["connector/objects/" + ref.key] = b"different bytes"
    before = dict(client.objects)
    with pytest.raises(ArtifactError):
        adapter(client).put_exact(ref, [data])
    assert client.objects == before


@pytest.mark.parametrize(
    "code", ["ConditionalRequestConflict", "SlowDown", "InternalError"]
)
def test_retry_keeps_conditional_create(code):
    client = ControlledS3()
    client.put_faults = [failure(code)]
    adapter(client).put_exact(reference(), [b"immutable bytes"])
    assert [kind for kind, _ in client.calls] == ["put", "put", "get"]


@pytest.mark.parametrize(
    "fault", [failure("SlowDown"), EndpointConnectionError(endpoint_url=SECRET)]
)
def test_upload_retry_exhaustion_has_no_readback_or_secret(fault):
    client = ControlledS3()
    client.put_faults = [fault] * 3
    with pytest.raises(ArtifactError) as error:
        adapter(client).put_exact(reference(), [b"immutable bytes"])
    assert SECRET not in str(error.value)
    assert len(client.calls) == 3 and not client.objects


def test_uncertain_completed_upload_can_retry_only_identical_object():
    client = ControlledS3()

    def uncertain(key, data):
        client.objects[key] = data
        raise EndpointConnectionError(endpoint_url=SECRET)

    client.put_faults = [uncertain]
    adapter(client).put_exact(reference(), [b"immutable bytes"])
    assert [kind for kind, _ in client.calls] == ["put", "put", "get"]


def test_partial_uncertain_upload_is_never_overwritten_or_verified():
    client = ControlledS3()

    def partial(key, data):
        client.objects[key] = data[:3]
        raise EndpointConnectionError(endpoint_url=SECRET)

    client.put_faults = [partial]
    with pytest.raises(ArtifactError):
        adapter(client).put_exact(reference(), [b"immutable bytes"])
    assert list(client.objects.values()) == [b"imm"]


@pytest.mark.parametrize(
    "transform",
    [
        lambda data: data[:-1],
        lambda data: b"X" * len(data),
        lambda data: data + b"extra",
    ],
)
def test_corrupt_truncated_or_oversized_readback_rejects_and_closes(transform):
    client = ControlledS3()
    client.read_transform = lambda key, data: transform(data)
    with pytest.raises(ArtifactError):
        adapter(client).put_exact(reference(), [b"immutable bytes"])
    assert all(stream.closed for stream in client.closed_bodies)


def test_missing_and_wrong_length_readback_are_safe():
    client = ControlledS3()
    with pytest.raises(ArtifactError) as error:
        list(adapter(client).read(reference()))
    assert SECRET not in str(error.value)
    client.length_transform = lambda key, data: len(data) + 1
    with pytest.raises(ArtifactError):
        adapter(client).put_exact(reference(), [b"immutable bytes"])
    assert all(stream.closed for stream in client.closed_bodies)


def test_get_retry_then_exhaustion():
    client = ControlledS3()
    store = adapter(client)
    store.put_exact(reference(), [b"immutable bytes"])
    client.get_faults = [failure("SlowDown")]
    assert b"".join(store.read(reference())) == b"immutable bytes"
    client.get_faults = [failure("SlowDown")] * 3
    with pytest.raises(ArtifactError):
        list(store.read(reference()))


@pytest.mark.parametrize("data", [b"", b"wrong", b"immutable bytes extra"])
def test_invalid_upload_never_reaches_sdk(data):
    client = ControlledS3()
    with pytest.raises(ArtifactError):
        adapter(client).put_exact(reference(), [data])
    assert not client.calls


def test_wire_caps_and_deadline_prevent_success():
    client = ControlledS3()
    with pytest.raises(ArtifactLimitError):
        adapter(client, transfer=TransferBounds(wire_bytes=15)).put_exact(
            reference(), [b"immutable bytes"]
        )
    assert len(client.calls) == 2  # PUT fits, readback exceeds remaining allowance.
    ticks = iter([0, 121])
    with pytest.raises(ArtifactLimitError):
        adapter(
            client,
            transfer=TransferBounds(elapsed_seconds=120),
            monotonic=lambda: next(ticks),
        ).put_exact(reference(), [b"immutable bytes"])
    assert len(client.calls) == 2


def test_graph_caps_and_untrusted_identity_before_sdk():
    client = ControlledS3()
    store = S3ArtifactStore(
        client, "test-bucket", "connector/", replace(ARTIFACT, objects=1)
    )
    store.put_exact(reference(), [b"immutable bytes"])
    with pytest.raises(ArtifactLimitError):
        store.put_exact(reference(b"second"), [b"second"])
    with pytest.raises(ArtifactError):
        list(store.read(StoredObject("https://arbitrary", reference().sha256, 15)))
    assert len(client.calls) == 2


def test_interrupted_stream_is_closed_and_safe():
    client = ControlledS3()
    store = adapter(client)
    store.put_exact(reference(), [b"immutable bytes"])
    with patch.object(
        StreamingBody, "read", side_effect=EndpointConnectionError(endpoint_url=SECRET)
    ):
        with pytest.raises(ArtifactError) as error:
            list(store.read(reference()))
    assert SECRET not in str(error.value)
    assert client.closed_bodies[-1].closed


def test_deadline_after_upload_response_cannot_start_readback():
    client = ControlledS3()
    now = [0]
    original = client.put_object

    def delayed(**kwargs):
        result = original(**kwargs)
        now[0] = 121
        return result

    client.put_object = delayed
    with pytest.raises(ArtifactLimitError):
        adapter(
            client,
            transfer=TransferBounds(elapsed_seconds=120),
            monotonic=lambda: now[0],
        ).put_exact(reference(), [b"immutable bytes"])
    assert [kind for kind, _ in client.calls] == ["put"]
    assert len(client.objects) == 1  # No acceptance or deletion after late PUT.


def test_deadline_after_get_response_closes_body_without_success():
    client = ControlledS3()
    now = [0]
    store = adapter(
        client, transfer=TransferBounds(elapsed_seconds=120), monotonic=lambda: now[0]
    )
    store.put_exact(reference(), [b"immutable bytes"])
    original = client.get_object

    def delayed(**kwargs):
        result = original(**kwargs)
        now[0] = 121
        return result

    client.get_object = delayed
    with pytest.raises(ArtifactLimitError):
        list(store.read(reference()))
    assert client.closed_bodies[-1].closed


def test_logs_distinguish_identical_skip_from_conflicting_bytes(caplog):
    caplog.set_level(logging.INFO, logger="outage_explorer.connector")
    client, data = ControlledS3(), b"immutable bytes"
    ref = reference(data)
    adapter(client).put_exact(ref, [data])
    caplog.clear()
    adapter(client).put_exact(ref, [data])
    assert "action=compare_bytes" in caplog.text
    assert caplog.text.index("s3_readback_verified") < caplog.text.index(
        "s3_upload_skipped"
    )
    assert "reason=identical_existing_bytes" in caplog.text
    caplog.clear()
    client.objects["connector/objects/" + ref.key] = b"X" * len(data)
    with pytest.raises(ArtifactError):
        adapter(client).put_exact(ref, [data])
    assert "reason=checksum_mismatch action=abort_preserve_existing" in caplog.text
    assert (
        "s3_upload_skipped" not in caplog.text
        and "s3_object_verified" not in caplog.text
    )
    assert SECRET not in caplog.text and "immutable bytes" not in caplog.text


def test_retry_logging_does_not_include_sdk_error_or_url(caplog):
    caplog.set_level(logging.INFO, logger="outage_explorer.connector")
    client = ControlledS3()
    client.put_faults = [EndpointConnectionError(endpoint_url=SECRET)]
    adapter(client).put_exact(reference(), [b"immutable bytes"])
    assert "s3_create_retry" in caplog.text and "attempt=2" in caplog.text
    assert SECRET not in caplog.text
