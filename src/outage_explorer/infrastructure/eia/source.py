"""Sequential, bounded EIA retrieval. Live transport wiring remains a phase-6 gate.

A caller owns the injected HTTPX transport's lifetime. Direct transport requests
avoid Client's URL logging (EIA requires api_key in the URL). Transports must not
log requests or untrusted response headers; no network transport is constructed
here and imports do not configure logging or perform I/O.
"""

import hashlib
import json
import logging
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from functools import partial
from threading import RLock
from uuid import uuid4

import httpx

from outage_explorer.application.ports.candidates import SanitizedPage
from outage_explorer.application.ports.source import (
    PageRequest,
    SourceBounds,
    SourceError,
    SourceLimitError,
    SourceMetadata,
    SourceQuality,
    SourceRequest,
)
from outage_explorer.domain.refresh import Origin
from outage_explorer.infrastructure.connector_workers import BoundedConnectorWorkers
from outage_explorer.infrastructure.eia.budget import SourceRunBudget
from outage_explorer.infrastructure.eia.quality import reconcile
from outage_explorer.infrastructure.eia.rate_limit import (
    SourceRateLimiter,
    wait_for_retry,
)
from outage_explorer.infrastructure.eia.sanitization import Sanitizer, parse_json
from outage_explorer.infrastructure.eia.transport import source_response

_LOG = logging.getLogger("outage_explorer.connector.eia")

_BASE = "https://api.eia.gov/v2/nuclear-outages/"
_MEASUREMENTS = ("capacity", "outage", "percentOutage")
_TRANSIENT = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
)


def _encoded(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError):
        raise SourceError("Invalid source evidence representation") from None


def _facility_order(value: str) -> tuple[int, int, str]:
    """Compare EIA digit-only facilities by magnitude without changing identity.

    Live EIA returns 46 before 204. A length/text key avoids integer conversion
    and preserves arbitrary-width/zero-prefixed source strings in the evidence.
    Nondigit identifiers retain text ordering after numeric identifiers.
    """
    if value.isascii() and value.isdecimal():
        magnitude = value.lstrip("0") or "0"
        return (0, len(magnitude), magnitude)
    return (1, 0, value)


@dataclass(frozen=True)
class _Fetched:
    offset: int
    parameters: dict[str, str]
    result: tuple[dict[str, object], int, tuple[str, ...], tuple[str, ...]]
    request_id: str
    received_at: datetime


class EiaSource:
    """Single-use, sequential retrieval with caller-supplied measured/test budgets."""

    def __init__(
        self,
        request: SourceRequest,
        bounds: SourceBounds,
        transport: httpx.BaseTransport,
        api_key: str,
        *,
        other_secrets: tuple[str, ...] = (),
        budget: SourceRunBudget | None = None,
        page_workers: int = 1,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._lock = RLock()
        self._fetch_count = self._fetched_rows = 0
        self._page_workers = BoundedConnectorWorkers(
            page_workers, None if budget is None else budget.cancelled
        )
        self.budget = budget
        self._rate_limiter = (
            budget.rate_limiter
            if budget is not None
            else SourceRateLimiter(bounds.request_interval_milliseconds, monotonic)
        )
        self.request = request
        self.bounds = bounds
        self._transport = transport
        self._api_key = api_key
        self._sanitize = Sanitizer((api_key, *other_secrets), bounds)
        for value in (
            request.run_id,
            request.retrieval_id,
            request.contract_id,
            request.transformation_id,
        ):
            if self._sanitize.text(value) != value:
                raise SourceError("Unsafe retrieval identity")
        if (
            request.interval.end - request.interval.start
        ).days + 1 > bounds.interval_days:
            raise SourceLimitError("Exceeded source interval days")
        self._clock, self._sleep, self._now, self._jitter = (
            monotonic,
            sleep,
            now,
            jitter,
        )
        self._deadline = monotonic() + bounds.elapsed_seconds
        self._requests = self._bytes = self._output = self._position = (
            self._page_index
        ) = 0
        self._metadata: SourceMetadata | None = None
        self._quality: SourceQuality | None = None
        self._failed = False
        self._digests: set[str] = set()
        self._totals: list[str] = []
        self._dates: set[date] = set()
        self._entities: set[tuple[str, ...]] = set()
        self._last_sort: tuple[str, tuple[int, int, str], str] | None = None

    @property
    def quality(self) -> SourceQuality | None:
        return self._quality

    def _remaining(self) -> float:
        self._page_workers.check()
        remaining = self._deadline - self._clock()
        if self.budget is not None:
            remaining = min(remaining, self.budget.remaining())
        if remaining <= 0:
            raise SourceLimitError("Exceeded retrieval deadline")
        return remaining

    def _active(self) -> None:
        if self._failed or self._quality is not None:
            raise SourceError("Retrieval is already finished or failed")
        self._remaining()

    def _count_output(self, value: object) -> None:
        size = len(_encoded(value))
        if self.budget is not None:
            self.budget.charge("output_bytes", size)
        self._output += size
        if self._output > self.bounds.output_bytes:
            raise SourceLimitError("Exceeded sanitized output bytes")
        self._remaining()

    def _read(self, response: httpx.Response) -> bytes:
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise SourceError("Unsupported source content encoding")
        length = response.headers.get("content-length")
        if length is not None:
            if not length.isascii() or not length.isdecimal():
                raise SourceError("Invalid response content length")
            normalized = length.lstrip("0") or "0"
            maximum = str(self.bounds.response_bytes)
            if len(normalized) > len(maximum) or (
                len(normalized) == len(maximum) and normalized > maximum
            ):
                raise SourceLimitError("Exceeded source response bytes")
        result = bytearray()
        # HTTPX MockTransport may return an already buffered response. Real
        # transports provide a stream; both paths undergo the same accounting.
        chunks = (
            (response.content,) if response.is_stream_consumed else response.iter_raw()
        )
        for chunk in chunks:
            self._remaining()
            if self.budget is not None:
                self.budget.charge("total_bytes", len(chunk))
            with self._lock:
                self._bytes += len(chunk)
                if self._bytes > self.bounds.total_bytes:
                    raise SourceLimitError("Exceeded total source bytes")
            if len(result) + len(chunk) > self.bounds.response_bytes:
                raise SourceLimitError("Exceeded source response bytes")
            result.extend(chunk)
        self._remaining()
        return bytes(result)

    def _delay(
        self, attempt: int, retry_after: str | None, *, throttled: bool = False
    ) -> None:
        # Cap the exponent before expanding it; attempts itself is caller-bound.
        delay = min(
            self.bounds.backoff_seconds,
            self.bounds.backoff_base_seconds * 2 ** min(attempt - 1, 20),
        )
        delay *= 0.5 + min(1.0, max(0.0, self._jitter())) / 2
        if retry_after is not None:
            self._sanitize.text(retry_after)  # field budget, never retain header
            try:
                if retry_after.isascii() and retry_after.isdecimal():
                    requested = float(retry_after)
                else:
                    target = parsedate_to_datetime(retry_after)
                    if target.tzinfo is None:
                        raise ValueError
                    requested = max(0.0, (target - self._now()).total_seconds())
            except (ValueError, OverflowError, TypeError):
                raise SourceError("Invalid Retry-After") from None
            if requested > self.bounds.backoff_seconds:
                raise SourceLimitError("Retry-After exceeds backoff bound")
            delay = max(delay, requested)
        if delay >= self._remaining():
            raise SourceLimitError("Retry delay exceeds retrieval deadline")
        if throttled or retry_after is not None:
            self._rate_limiter.defer(delay)
        _LOG.info(
            "eia_backoff run=%s route=%s delay_seconds=%.3f shared=%s",
            self.request.run_id,
            self.request.route,
            delay,
            throttled or retry_after is not None,
        )
        wait_for_retry(delay, self._clock, self._remaining, self._sleep)

    def _get(
        self, path: str, parameters: dict[str, str]
    ) -> tuple[dict[str, object], int, tuple[str, ...], tuple[str, ...]]:
        failures: list[str] = []
        for attempt in range(1, self.bounds.attempts + 1):
            self._rate_limiter.acquire(self._remaining, self._sleep)
            if self.budget is not None:
                self.budget.charge("requests", 1)
            with self._lock:
                self._requests += 1
                if self._requests > self.bounds.requests:
                    raise SourceLimitError("Exceeded source requests")
            timeout = min(self.bounds.timeout_seconds, self._remaining())
            _LOG.info(
                "eia_request run=%s route=%s kind=%s offset=%s attempt=%d",
                self.request.run_id,
                self.request.route,
                "page" if parameters else "metadata",
                parameters.get("offset", "none"),
                attempt,
            )
            wire = httpx.Request(
                "GET",
                _BASE + path,
                params={**parameters, "api_key": self._api_key},
                headers={"accept": "application/json", "accept-encoding": "identity"},
                extensions={
                    "timeout": {
                        key: timeout for key in ("connect", "read", "write", "pool")
                    }
                },
            )
            request_size = len(str(wire.url).encode()) + sum(
                len(k) + len(v) for k, v in wire.headers.raw
            )
            if request_size > self.bounds.request_bytes:
                raise SourceLimitError("Exceeded source request bytes")
            retry_after = None
            try:
                with source_response(self._transport, wire) as response:
                    self._remaining()
                    # Redirects are all rejected. No credentials reach another
                    # origin, scheme, port, path or an unvalidated request.
                    body = self._read(response)
                    status = response.status_code
                    retry_after = response.headers.get("retry-after")
            except _TRANSIENT:
                failures.append("transient_transport")
            except httpx.HTTPError:
                raise SourceError("Nonretryable source transport failure") from None
            else:
                if status == 200:
                    parsed = parse_json(body, self.bounds)
                    sanitized = self._sanitize.sanitize(parsed)
                    if not isinstance(sanitized.value, dict):
                        raise SourceError("Invalid source envelope")
                    self._validate_echo(sanitized.value, path, parameters)
                    self._remaining()
                    return sanitized.value, attempt, tuple(failures), sanitized.paths
                if status != 429 and not 500 <= status < 600:
                    raise SourceError("Nonretryable source HTTP status")
                failures.append(f"http_{status}")
            if attempt == self.bounds.attempts:
                raise SourceLimitError("Exceeded source attempts") from None
            _LOG.warning(
                "eia_retry run=%s route=%s attempt=%d reason=%s",
                self.request.run_id,
                self.request.route,
                attempt,
                failures[-1],
            )
            self._delay(attempt, retry_after, throttled=failures[-1] == "http_429")
        raise AssertionError("Positive attempt bound required")

    def _validate_echo(
        self, envelope: dict[str, object], path: str, parameters: dict[str, str]
    ) -> None:
        # EIA documents request.command and request.params. Older captured
        # evidence omitted the echo; when supplied it must agree with the request.
        if "request" not in envelope:
            return
        echo = envelope["request"]
        if not isinstance(echo, dict):
            raise SourceError("Unusable source request echo")
        command = echo.get("command")
        expected = "/v2/nuclear-outages/" + path
        if command is not None and (
            not isinstance(command, str) or command.rstrip("/") != expected.rstrip("/")
        ):
            raise SourceError("Source request route mismatch")
        if "params" in echo:
            params = echo["params"]
            # EIA serializes an empty metadata parameter map as []. Keep that
            # evidence unchanged; data requests still require an object echo.
            if params == [] and not parameters and path == self.request.route + "/":
                return
            if not isinstance(params, dict):
                raise SourceError("Unusable source parameter echo")
            for key in ("frequency", "start", "end", "offset", "length"):
                if (
                    key in params
                    and key in parameters
                    and str(params[key]) != parameters[key]
                ):
                    raise SourceError("Source request parameter mismatch")

    def fetch_metadata(self) -> SourceMetadata:
        try:
            self._active()
            if self._metadata is not None:
                return self._metadata
            envelope, attempt, failures, paths = self._get(self.request.route + "/", {})
            response, _ = self._envelope(envelope)
            frequencies = response.get("frequency")
            data = response.get("data")
            if (
                response.get("id") != self.request.route
                or not isinstance(frequencies, list)
                or not any(
                    isinstance(item, dict) and item.get("id") == "daily"
                    for item in frequencies
                )
                or not isinstance(data, dict)
                or any(not isinstance(data.get(field), dict) for field in _MEASUREMENTS)
            ):
                raise SourceError("Unusable source metadata")
            saved = {"source": envelope, "attempt_failures": list(failures)}
            self._count_output(saved)
            metadata = SourceMetadata(
                self._identity(), self._now(), attempt, saved, paths
            )
            self._metadata = metadata
            _LOG.info(
                "eia_metadata_verified run=%s route=%s",
                self.request.run_id,
                self.request.route,
            )
            return metadata
        except SourceError:
            self._failed = True
            raise

    def _identity(self) -> str:
        identity = uuid4().hex
        if self._sanitize.text(identity) != identity:
            raise SourceError("Unsafe generated source identity")
        return identity

    def _envelope(self, envelope: dict[str, object]) -> tuple[dict[str, object], str]:
        response = envelope.get("response")
        version = envelope.get("apiVersion")
        if (
            not isinstance(response, dict)
            or not isinstance(version, str)
            or not version
            or "error" in envelope
            or "error" in response
        ):
            raise SourceError("Unusable source envelope")
        return response, version

    def _parameters(self, page: PageRequest) -> dict[str, str]:
        parameters = {
            "frequency": "daily",
            "start": self.request.interval.start.isoformat(),
            "end": self.request.interval.end.isoformat(),
            "offset": str(page.offset),
            "length": str(self.bounds.page_rows),
        }
        for index, field in enumerate(_MEASUREMENTS):
            parameters[f"data[{index}]"] = field
        for index, column in enumerate(self.request.sort_columns):
            parameters[f"sort[{index}][column]"] = column
            parameters[f"sort[{index}][direction]"] = "asc"
        return parameters

    def _observe(self, values: list[object]) -> None:
        for value in values:
            if not isinstance(value, dict) or "_source_redacted_paths" in value:
                # Altered rows remain received evidence and are excluded by the
                # model; placeholders must never fabricate coverage or order.
                continue
            identifiers = tuple(
                value.get(field) for field in self.request.sort_columns[1:]
            )
            valid_entity = all(
                isinstance(item, str) and item.strip() for item in identifiers
            )
            entity = tuple(str(item) for item in identifiers) if valid_entity else ()
            if entity:
                self._entities.add(entity)
            period = value.get("period")
            if not isinstance(period, str):
                continue
            try:
                day = date.fromisoformat(period)
            except ValueError:
                continue  # malformed rows remain evidence for ordinary assessment
            if not self.request.interval.contains(day):
                raise SourceError("Source date outside requested interval")
            self._dates.add(day)
            if not valid_entity:
                continue
            sort = (
                day.isoformat(),
                _facility_order(entity[0]) if entity else (0, 0, ""),
                entity[1] if len(entity) > 1 else "",
            )
            if self._last_sort is not None and sort < self._last_sort:
                raise SourceError("Source ordering regression")
            self._last_sort = sort

    def fetch_page(self, request: PageRequest) -> SanitizedPage:
        try:
            return self._fetch_page(request)
        except SourceError:
            self._failed = True
            self._quality = None
            raise

    def _fetch_page(
        self,
        page: PageRequest,
        fetched: _Fetched | None = None,
        transport: tuple[object, ...] = (),
    ) -> SanitizedPage:
        self._active()
        if page.offset != self._position or page.page_index != self._page_index:
            raise SourceError("Nonsequential source page request")
        if self._page_index >= self.bounds.pages:
            raise SourceLimitError("Exceeded source pages")
        if fetched is None and self.budget is not None:
            self.budget.charge("pages", 1)
        metadata = self.fetch_metadata()
        parameters = self._parameters(page)
        envelope, attempt, failures, paths = (
            self._get(self.request.route + "/data/", parameters)
            if fetched is None
            else fetched.result
        )
        response, version = self._envelope(envelope)
        values, total = response.get("data"), response.get("total")
        if (
            not isinstance(values, list)
            or not isinstance(total, str)
            or not total
            or not total.isascii()
            or not total.isdecimal()
            or response.get("frequency") != "daily"
            or ("id" in response and response["id"] != self.request.route)
            or ("offset" in response and str(response["offset"]) != str(page.offset))
        ):
            raise SourceError("Unusable source page envelope")
        if (
            len(values) > self.bounds.page_rows
            or self._position + len(values) > self.bounds.rows
        ):
            raise SourceLimitError("Exceeded source rows")
        if fetched is None and self.budget is not None:
            self.budget.charge("rows", len(values))
        digest = hashlib.sha256(_encoded(values)).hexdigest()
        if values and digest in self._digests:
            raise SourceError("Repeated source page payload")
        self._digests.add(digest)
        if fetched is None:
            self._mark_rows(envelope, paths)
        self._observe(values)
        self._totals.append(total)
        quality = None
        if not values:
            quality = reconcile(
                self.request,
                self._position,
                tuple(self._totals),
                self._dates,
                self._entities,
            )
        saved_metadata = {
            "envelope": {
                **envelope,
                "response": {
                    key: value for key, value in response.items() if key != "data"
                },
            },
            "metadata": asdict(metadata)
            | {
                "retrieved_at": metadata.retrieved_at.isoformat(),
                "redacted_paths": list(metadata.redacted_paths),
            },
            "redacted_paths": list(paths),
            "attempt_failures": list(failures),
            "ordering_id": self.request.ordering_id,
            "pagination_contract": "offset-received-count-empty-terminator-unvalidated-live-v1",
        }
        origin = Origin(
            self.request.grain,
            self.request.run_id,
            self.request.retrieval_id,
            self._identity() if fetched is None else fetched.request_id,
            self._identity(),
            self._now() if fetched is None else fetched.received_at,
            page.page_index,
            0,
            page.offset,
            self.request.contract_id,
            self.request.transformation_id,
            self._identity(),
        )
        result = SanitizedPage(
            origin,
            self.request.interval,
            page.offset,
            self.bounds.page_rows,
            attempt,
            total,
            self.request.route,
            parameters,
            saved_metadata,
            version,
            tuple(values),
            transport,
        )
        self._count_output(
            {"parameters": parameters, "metadata": saved_metadata, "values": values}
        )
        self._position += len(values)
        self._page_index += 1
        self._quality = quality
        _LOG.info(
            "eia_page_collected run=%s route=%s page=%d offset=%d rows=%d terminal=%s",
            self.request.run_id,
            self.request.route,
            page.page_index,
            page.offset,
            len(values),
            quality is not None,
        )
        if quality is not None:
            _LOG.info(
                "eia_route_complete run=%s route=%s received=%d total_mismatch=%s total_changed=%s",
                self.request.run_id,
                self.request.route,
                quality.received,
                quality.count_mismatch,
                quality.totals_changed,
            )
        return result

    def _mark_rows(self, envelope: dict[str, object], paths: tuple[str, ...]) -> None:
        response = envelope["response"]
        assert isinstance(response, dict)
        values = response["data"]
        assert isinstance(values, list)
        # Paths use positional object indices, so even a credential in a key
        # cannot leak through path diagnostics. Every modified observation gets
        # an unexpected attribute: the existing contract excludes it explicitly.
        response_index = list(envelope).index("response")
        data_index = list(response).index("data")
        prefix = f"$/@{response_index}/value/@{data_index}/value/"
        for index, value in enumerate(values):
            row_prefix = prefix + str(index)
            row_paths = [
                path
                for path in paths
                if path == row_prefix or path.startswith(row_prefix + "/")
            ]
            if row_paths:
                if isinstance(value, dict):
                    if "_source_redacted_paths" in value:
                        raise SourceError("Reserved source redaction marker")
                    value["_source_redacted_paths"] = row_paths
                else:
                    values[index] = {
                        "_source_redacted_paths": row_paths,
                        "_source_redacted_value": value,
                    }

    def _prefetch(self, page: PageRequest) -> _Fetched:
        with self._lock:
            if self._fetch_count >= self.bounds.pages:
                raise SourceLimitError("Exceeded source pages including lookahead")
            self._fetch_count += 1
        if self.budget is not None:
            self.budget.charge("pages", 1)
        parameters = self._parameters(page)
        request_id = self._identity()
        result = self._get(self.request.route + "/data/", parameters)
        envelope, _, _, _ = result
        response, _ = self._envelope(envelope)
        values, total = response.get("data"), response.get("total")
        if (
            not isinstance(values, list)
            or not isinstance(total, str)
            or not total
            or not total.isascii()
            or not total.isdecimal()
            or response.get("frequency") != "daily"
            or ("id" in response and response["id"] != self.request.route)
            or ("offset" in response and str(response["offset"]) != str(page.offset))
        ):
            raise SourceError("Unusable prefetched source page envelope")
        if len(values) > self.bounds.page_rows:
            raise SourceLimitError("Exceeded prefetched page rows")
        with self._lock:
            self._fetched_rows += len(values)
            if self._fetched_rows > self.bounds.rows:
                raise SourceLimitError("Exceeded fetched rows including lookahead")
        if self.budget is not None:
            self.budget.charge("rows", len(values))
        self._mark_rows(envelope, result[3])
        return _Fetched(page.offset, parameters, result, request_id, self._now())

    def pages(self) -> Iterator[SanitizedPage]:
        if self._page_workers.workers == 1:
            while self._quality is None:
                yield self.fetch_page(PageRequest(self._position, self._page_index))
            return
        try:
            self.fetch_metadata()
            while self._quality is None:
                self._active()
                # A bounded window is joined before any canonical evidence yield.
                window = self._page_workers.run(
                    partial(
                        self._prefetch,
                        PageRequest(
                            self._position + index * self.bounds.page_rows,
                            self._page_index + index,
                        ),
                    )
                    for index in range(self._page_workers.workers)
                )
                used = []
                for response in window:
                    used.append(response.offset)
                    envelope = response.result[0]
                    data = envelope["response"]
                    assert isinstance(data, dict)
                    values = data["data"]
                    assert isinstance(values, list)
                    if len(values) < self.bounds.page_rows:
                        break
                audit = tuple(
                    {
                        "version": 1,
                        "offset": response.offset,
                        "parameters": response.parameters,
                        "request_id": response.request_id,
                        "received_at": response.received_at.isoformat(),
                        "attempt": response.result[1],
                        "failures": list(response.result[2]),
                        "redacted_paths": list(response.result[3]),
                        "envelope": response.result[0],
                        "used": response.offset in used,
                    }
                    for response in window
                )
                # Charge supplemental output, even when it cannot become modeled rows.
                for item in audit:
                    self._count_output(item)
                for index, response in enumerate(window):
                    if response.offset not in used:
                        continue
                    yield self._fetch_page(
                        PageRequest(self._position, self._page_index),
                        response,
                        audit if index == 0 else (),
                    )
        except BaseException:
            self._page_workers.cancelled.set()
            self._failed = True
            self._quality = None
            raise
