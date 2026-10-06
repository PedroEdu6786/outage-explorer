"""Bounded one-shot local Docker metrics for opt-in measurements only."""

import http.client
import io
import json
import re
import socket
from time import monotonic

from outage_explorer.application.errors import AnalyticalTimeoutError

LIMIT = 65_536


class StatsUnavailable(ValueError):
    def __init__(self, status):
        super().__init__("Container metrics unavailable")
        self.status = status


class _ResponseSocket:
    def __init__(self, data):
        self.data = data

    def makefile(self, mode):
        return io.BytesIO(self.data)


def decode_stats(raw, identity):
    response = http.client.HTTPResponse(_ResponseSocket(raw))
    response.begin()
    if response.status != 200:
        raise StatsUnavailable(response.status)
    body = response.read(LIMIT + 1)
    if len(body) > LIMIT:
        raise ValueError("Container metrics exceeded")
    value = json.loads(body)
    if value.get("id") != identity:
        raise ValueError("Container metrics identity mismatch")

    def number(value):
        if type(value) is not int or not 0 <= value < 2**64:
            raise ValueError("Invalid container counter")
        return value

    memory = number(value["memory_stats"].get("usage", 0))
    cpu = value["cpu_stats"]
    usage = number(cpu.get("cpu_usage", {}).get("total_usage", 0))
    system = number(cpu.get("system_cpu_usage", 0))
    cores = number(cpu.get("online_cpus", 0))
    # Total cgroup-accounted usage includes cache; it is not CLI cache-adjusted RSS.
    return memory, (usage, system, cores)


class ContainerStats:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.previous = {}

    def sample(self, identity):
        memory, current = container_stats(self.endpoint, identity)
        if identity not in self.previous and len(self.previous) >= 1024:
            raise ValueError("Container metrics identity budget exceeded")
        before = self.previous.get(identity)
        self.previous[identity] = current
        usage, system, cores = current
        percent = 0.0
        if before is not None and usage >= before[0] and system > before[1]:
            percent = (usage - before[0]) / (system - before[1]) * cores * 100
        if percent > 1_000_000:
            raise ValueError("Invalid container CPU counter")
        return memory, percent


def container_stats(endpoint, identity):
    if (
        not endpoint.startswith("unix:///")
        or re.fullmatch(r"[0-9a-f]{64}", identity) is None
    ):
        raise ValueError("Explicit local container metrics required")
    deadline = monotonic() + 2
    request = (
        f"GET /v1.51/containers/{identity}/stats?stream=false&one-shot=true HTTP/1.1\r\n"
        "Host: localhost\r\nConnection: close\r\n\r\n"
    ).encode("ascii")
    raw = bytearray()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(endpoint.removeprefix("unix://"))
            connection.sendall(request)
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise AnalyticalTimeoutError("Container metrics deadline")
                connection.settimeout(remaining)
                part = connection.recv(min(8192, LIMIT + 1 - len(raw)))
                if not part:
                    break
                raw.extend(part)
                if len(raw) > LIMIT:
                    raise ValueError("Container metrics exceeded")
    except TimeoutError:
        raise AnalyticalTimeoutError("Container metrics deadline") from None
    return decode_stats(bytes(raw), identity)
