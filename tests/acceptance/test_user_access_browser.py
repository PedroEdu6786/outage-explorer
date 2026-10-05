"""Real persistent Chromium profiles with controlled provider and server time."""

from datetime import timedelta
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

pytestmark = [pytest.mark.acceptance, pytest.mark.browser]


@pytest.fixture
def browser_server(harness_factory):
    # Bind ephemeral loopback before composing callback configuration.
    from flask import Flask

    server = make_server("127.0.0.1", 0, Flask("placeholder"), threaded=True)
    origin = "http://127.0.0.1:" + str(server.server_port)
    harness = harness_factory(origin)
    server.app = harness.app
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield harness
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def open_profile(playwright, profile, harness):
    executable = Path(playwright.chromium.executable_path)
    if not executable.is_file():
        pytest.fail(
            "Required browser missing: run .venv/bin/python -m playwright install chromium"
        )
    context = playwright.chromium.launch_persistent_context(str(profile), headless=True)

    def provider(route):
        state = parse_qs(urlsplit(route.request.url).query)["state"][0]
        route.fulfill(
            status=302,
            headers={
                "Location": harness.origin
                + "/api/auth/callback?"
                + urlencode({"code": "viewer", "state": state})
            },
        )

    context.route("https://login.test/oauth2/authorize?*", provider)
    return context


def login(context, harness):
    page = context.new_page()
    initial = context.request.get(harness.origin + "/api/auth/login", max_redirects=0)
    assert initial.status == 302
    page.goto(initial.headers["location"])
    page.wait_for_url(harness.origin + "/")
    return context.request.get(harness.origin + "/api/auth/session").json()


def test_close_reopen_fixed_expiry_logout_and_independent_profiles(
    browser_server, tmp_path
):
    harness = browser_server
    with sync_playwright() as playwright:
        first = open_profile(playwright, tmp_path / "first", harness)
        identity = login(first, harness)
        cookies = first.cookies()
        session = next(
            cookie for cookie in cookies if cookie["name"] == "outage_session"
        )
        assert session["httpOnly"] and session["sameSite"] == "Lax"
        assert session["domain"] == "127.0.0.1" and session["path"] == "/"
        assert "outage_session" not in first.pages[-1].evaluate("document.cookie")
        second = open_profile(playwright, tmp_path / "second", harness)
        other = login(second, harness)
        first.close()
        harness.clock.time += timedelta(minutes=30)
        reopened = open_profile(playwright, tmp_path / "first", harness)
        response = reopened.request.get(harness.origin + "/api/auth/session")
        assert response.status == 200
        assert response.json()["expires_at"] == identity["expires_at"]
        assert "set-cookie" not in response.headers
        assert len([r for r in harness.calls if r.method == "POST"]) == 2
        denied = reopened.request.post(
            harness.origin + "/api/auth/logout",
            headers={
                "Origin": "http://untrusted.test",
                "X-CSRF-Token": identity["csrf_token"],
            },
        )
        assert denied.status == 403
        assert (
            reopened.request.post(
                harness.origin + "/api/auth/logout", headers={"Origin": harness.origin}
            ).status
            == 403
        )
        assert reopened.request.get(harness.origin + "/api/auth/session").status == 200
        assert (
            reopened.request.post(
                harness.origin + "/api/auth/logout",
                headers={
                    "Origin": harness.origin,
                    "X-CSRF-Token": identity["csrf_token"],
                },
            ).status
            == 204
        )
        reopened.add_cookies([session])
        assert reopened.request.get(harness.origin + "/api/auth/session").status == 401
        reopened.close()
        revoked = open_profile(playwright, tmp_path / "first", harness)
        assert revoked.request.get(harness.origin + "/api/auth/session").status == 401
        assert (
            second.request.get(harness.origin + "/api/auth/session").json()[
                "expires_at"
            ]
            == other["expires_at"]
        )
        harness.clock.time += timedelta(minutes=30)
        assert second.request.get(harness.origin + "/api/auth/session").status == 401
        # Browser still holds an unexpired wall-clock cookie; server lease wins.
        assert next(c for c in second.cookies() if c["name"] == "outage_session")
        assert len([r for r in harness.calls if r.method == "POST"]) == 2
        revoked.close()
        second.close()
