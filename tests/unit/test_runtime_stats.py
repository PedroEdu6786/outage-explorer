import json
from unittest.mock import Mock

import pytest

from tests.runtime_stats import LIMIT, ContainerStats, container_stats, decode_stats

IDENTITY = "a" * 64


def wire(value, status=200):
    body = json.dumps(value).encode()
    return (
        f"HTTP/1.1 {status} Test\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body
    )


def stats():
    return {
        "id": IDENTITY,
        "memory_stats": {"usage": 1234},
        "cpu_stats": {
            "cpu_usage": {"total_usage": 100},
            "system_cpu_usage": 1000,
            "online_cpus": 2,
        },
    }


@pytest.mark.parametrize(
    "fault", [None, "identity", "negative", "boolean", "status", "large"]
)
def test_bounded_stats_identity_and_counters(fault):
    value = stats()
    if fault == "identity":
        value["id"] = "b" * 64
    elif fault in {"negative", "boolean"}:
        value["memory_stats"]["usage"] = -1 if fault == "negative" else True
    elif fault == "large":
        value["unused"] = "x" * (LIMIT + 1)
    raw = wire(value, 404 if fault == "status" else 200)
    if fault:
        with pytest.raises(ValueError):
            decode_stats(raw, IDENTITY)
    else:
        assert decode_stats(raw, IDENTITY) == (1234, (100, 1000, 2))


def test_one_shot_cpu_requires_two_samples_of_same_container(monkeypatch):
    read = Mock(
        side_effect=[
            (1234, (100, 1000, 2)),
            (2000, (300, 1400, 2)),
            (12, (99, 2000, 2)),
        ]
    )
    monkeypatch.setattr("tests.runtime_stats.container_stats", read)
    observer = ContainerStats("unix:///private-test")
    assert observer.sample(IDENTITY) == (1234, 0.0)
    assert observer.sample(IDENTITY) == (2000, 100.0)
    assert observer.sample("b" * 64) == (12, 0.0)


def test_transport_is_local_bounded_and_one_shot(monkeypatch):
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    connection.recv.side_effect = [wire(stats()), b""]
    factory = Mock(return_value=connection)
    monkeypatch.setattr("tests.runtime_stats.socket.socket", factory)
    assert container_stats("unix:///private-test", IDENTITY)[0] == 1234
    assert b"stream=false&one-shot=true" in connection.sendall.call_args.args[0]
    connection.connect.assert_called_once_with("/private-test")
    assert all(call.args[0] <= 2 for call in connection.settimeout.call_args_list)
    for endpoint, identity in [("tcp://remote", IDENTITY), ("unix:///test", "bad")]:
        with pytest.raises(ValueError):
            container_stats(endpoint, identity)


def test_transport_caps_before_decoding(monkeypatch):
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    connection.recv.return_value = b"x" * (LIMIT + 1)
    monkeypatch.setattr(
        "tests.runtime_stats.socket.socket", Mock(return_value=connection)
    )
    with pytest.raises(ValueError):
        container_stats("unix:///test", IDENTITY)
