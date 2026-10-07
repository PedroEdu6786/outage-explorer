"""Controlled HTTP streams through source retrieval and real Parquet replay.

Bounds below are deliberately tiny test budgets, not production measurements.
No test retrieves live EIA data or publishes to AWS/PostgreSQL.
"""

import json
import traceback
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from outage_explorer.application.ports.artifacts import ArtifactBounds
from outage_explorer.application.ports.source import (
    ORDERING_ID,
    PageRequest,
    SourceBounds,
    SourceError,
    SourceLimitError,
    SourceRequest,
)
from outage_explorer.domain.observations import SourceRecord, assess
from outage_explorer.domain.refresh import Interval, RefreshBounds, model_partition
from outage_explorer.infrastructure.eia.sanitization import Sanitizer
from outage_explorer.infrastructure.eia.source import EiaSource
from outage_explorer.infrastructure.parquet.evidence import (
    collect_resources,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore

SECRET = "synthetic-eia-secret-keep-private"
NOW = datetime(2026, 10, 3, tzinfo=UTC)
INTERVAL = Interval(date(2026, 9, 1), date(2026, 9, 30))
BOUNDS = SourceBounds(
    interval_days=30,
    page_rows=2,
    rows=10_000,
    pages=100,
    requests=200,
    attempts=3,
    request_bytes=4000,
    response_bytes=100_000,
    total_bytes=1_000_000,
    output_bytes=5_000_000,
    json_depth=20,
    json_nodes=20_000,
    field_bytes=20_000,
    elapsed_seconds=60,
    timeout_seconds=3,
    backoff_seconds=4,
)
ARTIFACT_BOUNDS = ArtifactBounds(
    100, 100, 1_000_000, 2_000_000, 30_000_000, 500, 100_000, 25
)
MODEL_BOUNDS = RefreshBounds(
    10_000, 10_000, 10_000, 30, 10_000, 100, 100, 100_000, 30, 100_000
)


class Clock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def __call__(self):
        return self.value

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.value += delay


def request(grain="national"):
    return SourceRequest(
        grain, INTERVAL, "run", "retrieval", "contract-v1", "transform-v1"
    )


def row(grain="national", **changes):
    value = {
        "period": "2026-09-01",
        "capacity": "+3.0000e0",
        "outage": "1",
        "percentOutage": "33.333333333333",
        "capacity-units": "megawatts",
        "outage-units": "megawatts",
        "percentOutage-units": "percent",
    }
    if grain != "national":
        value.update(facility="001", facilityName="Exact name ")
    if grain == "generator":
        value["generator"] = "01"
    return value | changes


def metadata(grain="national"):
    return {
        "apiVersion": "2.1.14",
        "response": {
            "id": request(grain).route,
            "frequency": [{"id": "daily"}],
            "data": {
                key: {"units": unit}
                for key, unit in (
                    ("capacity", "megawatts"),
                    ("outage", "megawatts"),
                    ("percentOutage", "percent"),
                )
            },
        },
    }


def page(values, total="3", **extra):
    return {
        "apiVersion": "2.1.14",
        "response": {"frequency": "daily", "total": total, "data": values, **extra},
    }


def response(payload=None, status=200, headers=None, body=None):
    body = json.dumps(payload).encode() if body is None else body
    return httpx.Response(status, headers=headers, stream=httpx.ByteStream(body))


def source(responses, grain="national", bounds=BOUNDS, clock=None):
    pending = iter(responses)
    calls = []
    clock = clock or Clock()

    def handle(wire):
        calls.append(wire)
        result = next(pending)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            return result(wire)
        return result

    adapter = EiaSource(
        request(grain),
        bounds,
        httpx.MockTransport(handle),
        SECRET,
        monotonic=clock,
        sleep=clock.sleep,
        now=lambda: NOW,
        jitter=lambda: 0.0,
    )
    return adapter, calls, clock


def standard(grain="national"):
    return [
        response(metadata(grain)),
        response(page([row(grain), row(grain, outage="2")])),
        response(page([row(grain, period="2026-09-02")])),
        response(page([])),
    ]


@pytest.mark.parametrize("grain", ["national", "facility", "generator"])
def test_full_short_and_empty_pages_retain_identity_and_coverage(grain):
    adapter, calls, _ = source(standard(grain), grain)
    pages = list(adapter.pages())
    assert [p.offset for p in pages] == [0, 2, 3]
    assert [p.origin.source_position for p in pages] == [0, 2, 3]
    assert [p.origin.page_index for p in pages] == [0, 1, 2]
    assert [len(p.values) for p in pages] == [2, 1, 0]
    assert len({p.origin.request_id for p in pages}) == 3
    assert len(calls) == 4
    assert all(call.url.host == "api.eia.gov" for call in calls)
    for call in calls[1:]:
        assert call.url.params["start"] == "2026-09-01"
        assert call.url.params["end"] == "2026-09-30"
        assert call.url.params["frequency"] == "daily"
        for i, column in enumerate(request(grain).sort_columns):
            assert call.url.params[f"sort[{i}][column]"] == column
        assert call.extensions["timeout"] == {
            key: 3 for key in ("connect", "read", "write", "pool")
        }
    quality = adapter.quality
    assert quality.received == 3
    assert quality.advertised_totals == ("3", "3", "3")
    assert quality.observed_dates == (date(2026, 9, 1), date(2026, 9, 2))
    assert quality.upstream_completeness == "unverified"
    assert quality.observed_entities == (
        ()
        if grain == "national"
        else (("001",),)
        if grain == "facility"
        else (("001", "01"),)
    )
    assert all(SECRET not in repr(p) for p in pages)
    assert pages[0].metadata["ordering_id"] == ORDERING_ID


@pytest.mark.parametrize("grain", ["national", "facility", "generator"])
def test_cross_page_aba_invalid_later_and_exact_parquet_replay(tmp_path, grain):
    a, b = row(grain), row(grain, outage="2")
    values = [
        a,
        b,
        a,
        row(grain, outage="invalid"),
        row(grain, period="2026-09-02", outage="0"),
    ]
    adapter, _, _ = source(
        [
            response(metadata(grain)),
            response(page(values[:2], "5")),
            response(page(values[2:4], "5")),
            response(page(values[4:], "5")),
            response(page([], "5")),
        ],
        grain,
    )
    store = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)
    bundle = collect_resources(store, adapter.pages())
    replay = list(bundle.rows)
    assert [item.value for item in replay] == values
    assert [item.origin.source_position for item in replay] == list(range(5))
    assert [item.origin.page_index for item in replay] == [0, 0, 1, 1, 2]
    assert [item.origin.row_index for item in replay] == [0, 1, 0, 1, 0]
    modeled = model_partition(grain, INTERVAL, replay, MODEL_BOUNDS)
    assert modeled.quality.received == 5
    assert modeled.quality.selected == 2
    assert modeled.quality.duplicate == 1
    assert modeled.quality.superseded == 1
    assert modeled.quality.excluded == 1
    assert modeled.rows[0].origin.source_position == 2
    assert (
        modeled.rows[0].observation.original
        == assess(SourceRecord(0, a), grain).observation.original
    )
    assert modeled.rows[1].result.fraction.numerator == 0
    assert adapter.quality.received == 5


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError(SECRET),
        httpx.ReadError(SECRET),
        httpx.ConnectTimeout(SECRET),
        httpx.ReadTimeout(SECRET),
        429,
        500,
        503,
        599,
    ],
)
def test_only_permitted_failures_retry_same_offset_without_duplicate_positions(failure):
    failed = (
        response({"error": SECRET}, status=failure)
        if isinstance(failure, int)
        else failure
    )
    adapter, calls, clock = source(
        [
            response(metadata()),
            failed,
            response(page([row()], "1")),
            response(page([], "1")),
        ]
    )
    pages = list(adapter.pages())
    assert pages[0].attempt == 2
    assert pages[0].origin.source_position == 0
    assert calls[1].url == calls[2].url
    assert len(clock.sleeps) == 1 and 0 < clock.sleeps[0] <= BOUNDS.backoff_seconds
    assert len(pages[0].metadata["attempt_failures"]) == 1
    assert SECRET not in repr(pages)


@pytest.mark.parametrize(
    "status", [201, 301, 302, 303, 307, 308, 400, 401, 403, 404, 408]
)
def test_other_statuses_and_redirects_fail_without_following(status):
    adapter, calls, _ = source(
        [
            response(metadata()),
            response(
                status=status, headers={"location": f"https://evil.example/{SECRET}"}
            ),
        ]
    )
    with pytest.raises(SourceError):
        list(adapter.pages())
    assert len(calls) == 2
    assert adapter.quality is None


@pytest.mark.parametrize(
    "location",
    [
        "/same-host/",
        "https://api.eia.gov/other/",
        "http://api.eia.gov/",
        "https://api.eia.gov:8443/",
        "https://evil.test/",
    ],
)
def test_all_redirect_locations_are_rejected(location):
    adapter, calls, _ = source([response(status=302, headers={"location": location})])
    with pytest.raises(SourceError):
        list(adapter.pages())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda p: None,
        lambda p: [],
        lambda p: {"response": {}},
        lambda p: p | {"apiVersion": ""},
        lambda p: p | {"error": "bad"},
        lambda p: page([], "-1"),
        lambda p: page([], "1.0"),
        lambda p: page([], "١"),
        lambda p: page([], 1),
        lambda p: page([], ""),
        lambda p: page({}, "0"),
        lambda p: page([], "0", frequency="monthly"),
        lambda p: page([], "0", id="other"),
        lambda p: page([], "0", offset="1"),
    ],
)
def test_bad_envelopes_and_totals_fail_without_retry(change):
    adapter, calls, _ = source(
        [response(metadata()), response(change(page([row()], "1")))]
    )
    with pytest.raises(SourceError):
        list(adapter.pages())
    assert len(calls) == 2


@pytest.mark.parametrize(
    "body",
    [
        b"{bad",
        b'{"response":1,"response":2}',
        b"[[[[[[[[[[[[[[[[[[[[[[1",
        b'{"bad":"\\ud800"}',
    ],
)
def test_bad_json_and_unicode_are_safe_failures(body):
    adapter, _, _ = source([response(body=body)])
    with pytest.raises(SourceError):
        list(adapter.pages())


@pytest.mark.parametrize(
    "modify",
    [
        lambda m: m["response"].update(id="other"),
        lambda m: m["response"].update(frequency=[]),
        lambda m: m["response"].update(data={}),
    ],
)
def test_metadata_is_required_and_validated(modify):
    payload = metadata()
    modify(payload)
    adapter, calls, _ = source([response(payload)])
    with pytest.raises(SourceError):
        list(adapter.pages())
    assert len(calls) == 1


@pytest.mark.parametrize("grain", ["national", "facility", "generator"])
def test_empty_repeated_out_of_window_and_regressing_pages_fail(grain):
    sequences = [
        [response(page([], "0"))],
        [response(page([row(grain)], "2")), response(page([row(grain)], "2"))],
        [response(page([row(grain, period="2026-10-01")], "1"))],
        [
            response(page([row(grain, period="2026-09-02")], "2")),
            response(page([row(grain)], "2")),
        ],
    ]
    for sequence in sequences:
        adapter, _, _ = source([response(metadata(grain)), *sequence], grain)
        with pytest.raises(SourceError):
            list(adapter.pages())
        assert adapter.quality is None
        with pytest.raises(SourceError, match="finished or failed"):
            adapter.fetch_page(PageRequest(0, 0))


@pytest.mark.parametrize("grain", ["facility", "generator"])
def test_opaque_identity_sort_regression_fails(grain):
    field = "facility" if grain == "facility" else "generator"
    values = [row(grain, **{field: "02"}), row(grain, **{field: "01"})]
    adapter, _, _ = source(
        [response(metadata(grain)), response(page(values, "2"))], grain
    )
    with pytest.raises(SourceError, match="ordering"):
        list(adapter.pages())


@pytest.mark.parametrize("grain", ["facility", "generator"])
def test_numeric_facility_order_across_pages_preserves_opaque_identifiers(
    tmp_path, grain
):
    # 46 -> 204 reproduced the live lexical-comparison bug. Leading-zero keys
    # remain distinct observations even when their numeric ordering keys tie.
    identifiers = ["00046", "46", "204", "1000", "99999999999999999999"]
    values = [row(grain, facility=identifier) for identifier in identifiers]
    adapter, _, _ = source(
        [response(metadata(grain))]
        + [response(page([value], "5")) for value in values]
        + [response(page([], "5"))],
        grain,
    )
    store = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)
    bundle = collect_resources(store, adapter.pages())
    replayed = list(bundle.rows)
    assert [record.value["facility"] for record in replayed] == identifiers
    assert len(adapter.quality.observed_entities) == 5
    modeled = model_partition(grain, INTERVAL, replayed, MODEL_BOUNDS)
    assert modeled.quality.selected == 5


@pytest.mark.parametrize("grain", ["facility", "generator"])
def test_numeric_facility_regression_across_pages_still_fails(grain):
    adapter, _, _ = source(
        [
            response(metadata(grain)),
            response(page([row(grain, facility="204")], "2")),
            response(page([row(grain, facility="46")], "2")),
        ],
        grain,
    )
    with pytest.raises(SourceError, match="ordering regression"):
        list(adapter.pages())
    assert adapter.quality is None


def test_generator_identifier_order_remains_textual():
    values = [
        row("generator", generator=value) for value in ("01", "1", "10", "2", "A")
    ]
    adapter, _, _ = source(
        [response(metadata("generator"))]
        + [response(page([value], "5")) for value in values]
        + [response(page([], "5"))],
        "generator",
    )
    assert [item.values[0]["generator"] for item in list(adapter.pages())[:-1]] == [
        "01",
        "1",
        "10",
        "2",
        "A",
    ]


@pytest.mark.parametrize("grain", ["national", "generator"])
@pytest.mark.parametrize("totals", [("2", "2"), ("1", "2"), ("9" * 5000, "9" * 5000)])
def test_nonfacility_inconsistent_totals_fail(grain, totals):
    adapter, _, _ = source(
        [
            response(metadata(grain)),
            response(page([row(grain)], totals[0])),
            response(page([], totals[1])),
        ],
        grain,
    )
    with pytest.raises(SourceError, match="totals inconsistent"):
        list(adapter.pages())
    assert adapter.quality is None


@pytest.mark.parametrize("received,advertised", [(1650, "2850"), (3, "9")])
@pytest.mark.parametrize("failed_page", [False, True])
def test_facility_mismatch_is_visible_but_never_excuses_failed_pages(
    received, advertised, failed_page
):
    values = [row("facility", facility=f"{i:04}") for i in range(received)]
    bounds = replace(
        BOUNDS,
        page_rows=1000,
        response_bytes=500_000,
        total_bytes=2_000_000,
        json_nodes=100_000,
    )
    pages = [
        response(page(values[i : i + 1000], advertised))
        for i in range(0, received, 1000)
    ]
    pages.append(
        response(status=403) if failed_page else response(page([], advertised))
    )
    adapter, _, _ = source([response(metadata("facility")), *pages], "facility", bounds)
    if failed_page:
        with pytest.raises(SourceError):
            list(adapter.pages())
        assert adapter.quality is None
    else:
        assert sum(len(p.values) for p in adapter.pages()) == received
        assert adapter.quality.received == received
        assert adapter.quality.count_mismatch
        assert adapter.quality.diagnostics == ("facility_total_diagnostic_v1",)
        assert len(adapter.quality.observed_entities) == received


def test_changing_facility_totals_are_preserved_without_sum():
    adapter, _, _ = source(
        [
            response(metadata("facility")),
            response(page([row("facility")], "7")),
            response(page([], "9")),
        ],
        "facility",
    )
    list(adapter.pages())
    assert adapter.quality.advertised_totals == ("7", "9")
    assert adapter.quality.totals_changed


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("interval_days", 1, "interval"),
        ("page_rows", 1, "rows"),
        ("rows", 1, "rows"),
        ("pages", 1, "pages"),
        ("requests", 1, "requests"),
        ("request_bytes", 1, "request bytes"),
        ("response_bytes", 1, "response bytes"),
        ("total_bytes", 1, "total source bytes"),
        ("output_bytes", 1, "output bytes"),
        ("json_depth", 1, "JSON depth"),
        ("json_nodes", 1, "JSON complexity"),
        ("field_bytes", 1, "field bytes"),
    ],
)
def test_each_count_size_and_complexity_cap_fails_retrieval(field, value, match):
    with pytest.raises(SourceLimitError, match=match):
        adapter, _, _ = source(standard(), bounds=replace(BOUNDS, **{field: value}))
        list(adapter.pages())


def test_attempt_limit_counts_failed_response_bytes_and_sanitizes_failure(caplog):
    adapter, calls, clock = source(
        [response(metadata()), *[response({"error": SECRET}, 503) for _ in range(3)]]
    )
    with pytest.raises(SourceLimitError, match="attempts") as captured:
        list(adapter.pages())
    assert len(calls) == 4
    assert len(clock.sleeps) == 2
    assert SECRET not in "".join(traceback.format_exception(captured.value))
    assert SECRET not in caplog.text
    adapter, _, _ = source(
        [
            response(metadata()),
            response(body=b"x" * 300, status=503),
            response(body=b"x" * 300, status=503),
        ],
        bounds=replace(BOUNDS, total_bytes=700),
    )
    with pytest.raises(SourceLimitError, match="total source bytes"):
        list(adapter.pages())


@pytest.mark.parametrize("retry_after", ["10", "Sat, 03 Oct 2026 00:00:10 GMT"])
def test_retry_after_cannot_exceed_backoff_cap(retry_after):
    adapter, _, _ = source([response(status=429, headers={"retry-after": retry_after})])
    with pytest.raises(SourceLimitError, match="backoff"):
        list(adapter.pages())


@pytest.mark.parametrize("retry_after", ["2", "Sat, 03 Oct 2026 00:00:02 GMT"])
def test_retry_after_is_honored_within_bounds(retry_after):
    adapter, _, clock = source(
        [response(status=429, headers={"retry-after": retry_after}), *standard()]
    )
    list(adapter.pages())
    assert clock.sleeps == [2]


def test_total_deadline_covers_consumer_pause_request_and_sleep():
    clock = Clock()
    adapter, _, _ = source(standard(), clock=clock)
    iterator = adapter.pages()
    next(iterator)
    clock.value = 60
    with pytest.raises(SourceLimitError, match="deadline"):
        next(iterator)
    adapter, _, _ = source(
        [response(status=503)], bounds=replace(BOUNDS, elapsed_seconds=1)
    )
    adapter._jitter = lambda: 1.0
    with pytest.raises(SourceLimitError, match="deadline"):
        list(adapter.pages())
    clock = Clock()

    def delayed(_):
        clock.value = 61
        return response(metadata())

    adapter, _, _ = source([delayed], clock=clock)
    with pytest.raises(SourceLimitError, match="deadline"):
        list(adapter.pages())


class Chunks(httpx.SyncByteStream):
    def __init__(self, chunks, clock=None):
        self.chunks = chunks
        self.clock = clock
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            if self.clock:
                self.clock.value += 31
            yield chunk

    def close(self):
        self.closed = True


def test_stream_deadline_and_byte_cap_close_response():
    for deadline in (False, True):
        clock = Clock()
        chunks = Chunks([b"x" * 600, b"y" * 600], clock if deadline else None)
        adapter, _, _ = source(
            [httpx.Response(200, stream=chunks)],
            clock=clock,
            bounds=replace(BOUNDS, response_bytes=1000),
        )
        with pytest.raises(
            SourceLimitError, match="deadline" if deadline else "response bytes"
        ):
            list(adapter.pages())
        assert chunks.closed


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "zstd"])
def test_compression_rejected_before_decompression(encoding):
    adapter, _, _ = source(
        [response(body=b"untrusted", headers={"content-encoding": encoding})]
    )
    with pytest.raises(SourceError, match="encoding"):
        list(adapter.pages())


def test_nested_secret_keys_values_and_paths_are_safe_and_observations_excluded(
    tmp_path,
):
    values = [
        row("facility", facilityName=SECRET),
        row(
            "facility",
            extra={SECRET: ["Bearer " + SECRET, {"password": "unknown-secret"}]},
        ),
    ]
    meta = metadata("facility") | {
        "echo": {
            "api_key": SECRET,
            "url": f"https://api.eia.gov?api_key={SECRET}",
            SECRET: "value",
        }
    }
    data = page(values, "2") | {"nested": [{"Authorization": "Bearer unknown-token"}]}
    adapter, _, _ = source(
        [response(meta), response(data), response(page([], "2"))], "facility"
    )
    store = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)
    bundle = collect_resources(store, adapter.pages())
    replay = list(bundle.rows)
    assert all("_source_redacted_paths" in item.value for item in replay)
    assert all(
        assess(SourceRecord(i, item.value), "facility").observation is None
        for i, item in enumerate(replay)
    )
    all_records = list(bundle.rows)
    assert not list(tmp_path.iterdir())
    for secret in (SECRET, "unknown-secret", "unknown-token"):
        assert secret not in repr(all_records)
    assert replay[0].value["capacity"] == "+3.0000e0"


def test_sanitization_key_collisions_and_unsafe_ids_fail_safely():
    sanitizer = Sanitizer((SECRET,), BOUNDS)
    with pytest.raises(SourceError, match="collision"):
        sanitizer.sanitize({SECRET: "first", "[REDACTED]": "second"})
    with pytest.raises(SourceError, match="identity"):
        EiaSource(
            replace(request(), run_id=SECRET),
            BOUNDS,
            httpx.MockTransport(lambda _: None),
            SECRET,
        )


@pytest.mark.parametrize("field", list(asdict(BOUNDS)))
def test_invalid_bounds_rejected(field):
    with pytest.raises(SourceError):
        replace(BOUNDS, **{field: 0})


def test_invalid_route_frequency_order_and_page_positions_fail_before_io():
    for changes in (
        {"grain": "other"},
        {"frequency": "monthly"},
        {"ordering_id": "recency"},
    ):
        with pytest.raises(SourceError):
            replace(request(), **changes)
    with pytest.raises(SourceError):
        replace(BOUNDS, page_rows=5001)
    with pytest.raises(SourceError):
        PageRequest(-1, 0)
    adapter, calls, _ = source(standard())
    with pytest.raises(SourceError, match="Nonsequential"):
        adapter.fetch_page(PageRequest(1, 0))
    assert not calls


def test_recorded_fixture_envelopes_supported():
    for grain in ("national", "facility", "generator"):
        directory = Path("data/verification") / f"{grain}-2026-09"
        saved_metadata = json.loads((directory / "metadata.json").read_text())
        saved_data = json.loads((directory / f"{grain}.json").read_text())
        values = saved_data["response"]["data"]
        # Reorder recorded observations to exercise the proposed request sort.
        # This is fixture replay, not proof of live ordering stability.
        # These recorded fixtures have exclusively numeric facility IDs. Use
        # numeric fixture sorting only; adapter/model evidence keeps the strings.
        values.sort(
            key=lambda r: (
                r["period"],
                int(r.get("facility", "0")),
                r.get("generator", ""),
            )
        )
        bounds = replace(
            BOUNDS,
            page_rows=5000,
            response_bytes=2_000_000,
            total_bytes=4_000_000,
            output_bytes=10_000_000,
            json_nodes=200_000,
        )
        adapter, _, _ = source(
            [
                response(saved_metadata),
                response(saved_data),
                response(page([], saved_data["response"]["total"])),
            ],
            grain,
            bounds,
        )
        assert sum(len(p.values) for p in adapter.pages()) == len(values)


@pytest.mark.parametrize(
    "failure",
    [
        httpx.WriteError(SECRET),
        httpx.PoolTimeout(SECRET),
        httpx.RemoteProtocolError(SECRET),
    ],
)
def test_nonretryable_transport_failure_is_safe_and_fatal(failure):
    adapter, calls, _ = source([response(metadata()), failure])
    with pytest.raises(SourceError, match="Nonretryable") as captured:
        list(adapter.pages())
    assert len(calls) == 2
    assert SECRET not in "".join(traceback.format_exception(captured.value))
    assert adapter.quality is None
    with pytest.raises(SourceError, match="finished or failed"):
        adapter.fetch_metadata()


class InterruptedStream(Chunks):
    def __iter__(self):
        yield b"partial response with " + SECRET.encode()
        raise httpx.ReadError(SECRET)


def test_partial_stream_error_counts_bytes_and_retry_keeps_page_identity():
    stream = InterruptedStream([])
    adapter, calls, _ = source(
        [
            response(metadata()),
            httpx.Response(200, stream=stream),
            response(page([row()], "1")),
            response(page([], "1")),
        ]
    )
    pages = list(adapter.pages())
    assert stream.closed
    assert pages[0].attempt == 2
    assert pages[0].origin.source_position == 0
    assert calls[1].url == calls[2].url
    assert pages[0].metadata["attempt_failures"] == ["transient_transport"]
    assert SECRET not in repr(pages)
    expected = len(json.dumps(metadata()).encode()) + len(
        b"partial response with " + SECRET.encode()
    )
    # Exhaust precisely while counting the failed read's prefix, before retry.
    adapter, calls, _ = source(
        [response(metadata()), httpx.Response(200, stream=InterruptedStream([]))],
        bounds=replace(BOUNDS, total_bytes=expected - 1),
    )
    with pytest.raises(SourceLimitError, match="total source bytes"):
        list(adapter.pages())
    assert len(calls) == 2


@pytest.mark.parametrize("grain", ["national", "facility", "generator"])
def test_leading_zero_totals_have_equal_numeric_meaning(grain):
    adapter, _, _ = source(
        [
            response(metadata(grain)),
            response(page([row(grain)], "0001")),
            response(page([], "1")),
        ],
        grain,
    )
    list(adapter.pages())
    assert adapter.quality.advertised_totals == ("0001", "1")
    assert not adapter.quality.totals_changed
    assert not adapter.quality.count_mismatch


def test_observed_entity_coverage_survives_invalid_date_or_measurement():
    values = [
        row("facility", facility="001", period="bad-date"),
        row("facility", facility="002", outage="bad"),
    ]
    adapter, _, _ = source(
        [
            response(metadata("facility")),
            response(page(values, "2")),
            response(page([], "2")),
        ],
        "facility",
    )
    pages = list(adapter.pages())
    assert adapter.quality.observed_entities == (("001",), ("002",))
    assert adapter.quality.observed_dates == (date(2026, 9, 1),)
    assert all(
        assess(SourceRecord(i, value), "facility").observation is None
        for i, value in enumerate(pages[0].values)
    )


@pytest.mark.parametrize(
    "length,error",
    [("-1", SourceError), ("bad", SourceError), ("9" * 5000, SourceLimitError)],
)
def test_invalid_and_huge_content_lengths_fail_safely(length, error):
    adapter, _, _ = source([response(metadata(), headers={"content-length": length})])
    with pytest.raises(error):
        list(adapter.pages())


def test_timeout_is_bounded_by_remaining_retrieval_deadline():
    clock = Clock()
    adapter, calls, _ = source(standard(), clock=clock)
    clock.value = 58
    list(adapter.pages())
    assert all(
        call.extensions["timeout"]
        == {key: 2 for key in ("connect", "read", "write", "pool")}
        for call in calls
    )


def test_metadata_fetch_is_cached_and_receives_attempt_diagnostics():
    adapter, calls, _ = source([response(status=503), *standard()])
    meta = adapter.fetch_metadata()
    assert adapter.fetch_metadata() is meta
    assert meta.attempt == 2
    assert meta.envelope["attempt_failures"] == ["http_503"]
    assert len(calls) == 2
    list(adapter.pages())
    assert len(calls) == 5


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "opaque",
        17,
        {"period": "bad-date"},
        row(**{"capacity-units": "MW"}),
        row(capacity=None),
        row(extra="unexpected"),
    ],
)
def test_malformed_observations_are_preserved_for_exclusion(value):
    adapter, _, _ = source(
        [response(metadata()), response(page([value], "1")), response(page([], "1"))]
    )
    pages = list(adapter.pages())
    assert pages[0].values == (value,)
    assert assess(SourceRecord(0, value), "national").observation is None
    assert adapter.quality.received == 1


def test_nonfinite_numbers_never_reach_artifact_output():
    adapter, _, _ = source(
        [
            response(metadata()),
            response(body=b'{"response":{"data":[NaN]},"apiVersion":"2"}'),
        ]
    )
    with pytest.raises(SourceError):
        list(adapter.pages())


def test_configured_secrets_in_scalar_values_and_encoded_strings_are_redacted():
    secret = "opaque/credential+test"
    sanitizer = Sanitizer((secret,), BOUNDS)
    cleaned = sanitizer.sanitize(
        {
            "nested": [secret, "opaque%2Fcredential%2Btest", {"x": secret}],
            secret: "value",
        }
    )
    assert secret not in repr(cleaned)
    assert "opaque%2Fcredential%2Btest" not in repr(cleaned)
    assert cleaned.paths == (
        "$/@0/value/0",
        "$/@0/value/1",
        "$/@0/value/2/@0/value",
        "$/@1/key",
    )


@pytest.mark.parametrize(
    "echo",
    [
        {"command": "/v2/nuclear-outages/generator-nuclear-outages/data/"},
        {"params": {"frequency": "monthly"}},
        {"params": {"start": "2026-08-01"}},
        {"params": {"end": "2026-10-01"}},
        {"params": {"offset": 7}},
        {"params": {"length": 99}},
        {"params": []},
        [],
    ],
)
def test_conflicting_echoed_request_fails(echo):
    payload = page([row()], "1") | {"request": echo}
    adapter, calls, _ = source([response(metadata()), response(payload)])
    with pytest.raises(SourceError):
        list(adapter.pages())
    assert len(calls) == 2


def test_matching_echo_is_retained_sanitized():
    payload = page([row()], "1") | {
        "request": {
            "command": "/v2/nuclear-outages/us-nuclear-outages/data/",
            "params": {"api_key": SECRET, "offset": 0, "frequency": "daily"},
        }
    }
    adapter, _, _ = source(
        [response(metadata()), response(payload), response(page([], "1"))]
    )
    pages = list(adapter.pages())
    assert pages[0].metadata["envelope"]["request"]["params"]["api_key"] == "[REDACTED]"
    assert SECRET not in repr(pages)


@pytest.mark.parametrize("grain", ["national", "facility", "generator"])
def test_empty_metadata_parameter_array_is_retained_and_data_retrieval_continues(grain):
    # Observed live: EIA encodes an empty metadata params object as [].
    payload = metadata(grain) | {
        "request": {
            "command": f"/v2/nuclear-outages/{request(grain).route}/",
            "params": [],
        }
    }
    adapter, calls, _ = source(
        [response(payload), response(page([row(grain)], "1")), response(page([], "1"))],
        grain,
    )
    pages = list(adapter.pages())
    assert [len(item.values) for item in pages] == [1, 0]
    assert adapter.quality.received == 1 and len(calls) == 3
    assert (
        pages[0].metadata["metadata"]["envelope"]["source"]["request"]["params"] == []
    )


@pytest.mark.parametrize("params", [["unexpected"], [0], "", None, False])
def test_other_nonobject_metadata_parameter_echoes_remain_invalid(params):
    payload = metadata() | {"request": {"params": params}}
    adapter, calls, _ = source([response(payload)])
    with pytest.raises(SourceError, match="Unusable source parameter echo"):
        adapter.fetch_metadata()
    assert len(calls) == 1 and adapter.quality is None


def test_empty_metadata_params_does_not_bypass_route_validation():
    payload = metadata() | {
        "request": {"command": "/v2/nuclear-outages/wrong-route/", "params": []}
    }
    adapter, _, _ = source([response(payload)])
    with pytest.raises(SourceError, match="Source request route mismatch"):
        adapter.fetch_metadata()


def test_redacted_identifier_cannot_fabricate_coverage_or_sort_regression():
    values = [row("facility", facility="abc"), row("facility", facility=SECRET)]
    adapter, _, _ = source(
        [
            response(metadata("facility")),
            response(page(values, "2")),
            response(page([], "2")),
        ],
        "facility",
    )
    pages = list(adapter.pages())
    assert pages[0].values[1]["facility"] == "[REDACTED]"
    assert "_source_redacted_paths" in pages[0].values[1]
    assert adapter.quality.received == 2
    assert adapter.quality.observed_entities == (("abc",),)
