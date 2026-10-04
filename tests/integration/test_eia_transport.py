"""Actual HTTPX/httpcore wire handling with controlled in-memory network I/O."""

import logging
from concurrent.futures import ThreadPoolExecutor

import httpcore
import httpx
import pytest

from outage_explorer.infrastructure.eia.transport import source_response

SECRET = "synthetic-wire-credential"


def transport_for(buffer):
    transport = httpx.HTTPTransport(trust_env=False)
    # Exercise the real HTTP/1.1 parsing and trace log paths without sockets.
    transport._pool = httpcore.ConnectionPool(
        network_backend=httpcore.MockBackend(buffer)
    )
    return transport


def request():
    return httpx.Request("GET", f"https://api.eia.gov/v2/example/?api_key={SECRET}")


def test_real_httpcore_header_logs_are_suppressed_only_during_source(caplog):
    caplog.set_level(logging.DEBUG)
    wire = (
        f"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
        f"X-Echo: {SECRET}\r\nSet-Cookie: secret-cookie\r\n\r\n{{}}"
    ).encode()
    with transport_for([wire]) as transport:
        with source_response(transport, request()) as response:
            assert response.read() == b"{}"
            # The filter does not rewrite headers needed by the adapter.
            assert response.headers["x-echo"] == SECRET
    assert SECRET not in caplog.text
    assert "secret-cookie" not in caplog.text
    logging.getLogger("httpcore.http11").debug("outside-source-diagnostic")
    assert "outside-source-diagnostic" in caplog.text


def test_real_protocol_error_cannot_log_source_content(caplog):
    caplog.set_level(logging.DEBUG)
    # h11 includes malformed header bytes in its protocol error message.
    wire = f"HTTP/1.1 200 OK\r\n{SECRET}\r\n\r\n".encode()
    with transport_for([wire]) as transport:
        with pytest.raises(httpx.RemoteProtocolError):
            with source_response(transport, request()):
                pytest.fail("Malformed response must not be accepted")
    assert SECRET not in caplog.text
    logging.getLogger("httpcore.http11").debug("diagnostic-after-error")
    assert "diagnostic-after-error" in caplog.text


def test_source_scope_covers_stream_and_close_without_muting_other_threads(caplog):
    caplog.set_level(logging.DEBUG)
    logger = logging.getLogger("httpcore.http11")

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            logger.debug("stream %s", SECRET)
            yield b"{}"

        def close(self):
            logger.debug("close %s", SECRET)

    def handle(wire):
        logger.debug("request %s", SECRET)
        return httpx.Response(200, stream=Stream())

    with ThreadPoolExecutor(max_workers=1) as executor:
        with httpx.MockTransport(handle) as transport:
            with source_response(transport, request()) as response:
                executor.submit(logger.debug, "unrelated-thread-diagnostic").result()
                logging.getLogger("outage_explorer").info("application-diagnostic")
                assert response.read() == b"{}"
    assert SECRET not in caplog.text
    assert "unrelated-thread-diagnostic" in caplog.text
    assert "application-diagnostic" in caplog.text


def test_nested_source_scopes_restore_outer_protection(caplog):
    caplog.set_level(logging.DEBUG)
    logger = logging.getLogger("httpx")
    with httpx.MockTransport(
        lambda wire: httpx.Response(200, content=b"{}")
    ) as transport:
        with source_response(transport, request()):
            with source_response(transport, request()):
                logger.info("inner %s", SECRET)
            logger.info("outer %s", SECRET)
    logger.info("after-both-scopes")
    assert SECRET not in caplog.text
    assert "after-both-scopes" in caplog.text
