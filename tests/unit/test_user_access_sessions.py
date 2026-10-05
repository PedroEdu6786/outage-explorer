"""Application lifecycle without Flask, AWS, connector, or analytical data."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from outage_explorer.application.dto import VerifiedIdentity
from outage_explorer.application.errors import AccessStoreError, UnauthenticatedError
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.login import LoginService
from outage_explorer.domain.access import Role, SeededUser, Session
from outage_explorer.infrastructure.security import RandomSecurityMaterial

NOW = datetime(2026, 10, 4, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.time = NOW

    def now(self):
        return self.time


class Store:
    def __init__(self):
        self.user = SeededUser(
            "one", "https://issuer.test/pool", "subject", "viewer@test", Role.VIEWER
        )
        self.sessions = {}
        self.attempts = {}
        self.failure = False

    def find_user(self, issuer, subject):
        return (
            self.user
            if self.user
            and (issuer, subject)
            == (self.user.identity_issuer, self.user.identity_subject)
            else None
        )

    def create_session(self, digest, user_id, established, expiry):
        self.sessions[digest] = Session(digest, self.user, established, expiry)

    def resolve_session(self, digest, now):
        if self.failure:
            raise AccessStoreError("Store unavailable")
        session = self.sessions.get(digest)
        return replace(session, user=self.user) if session and self.user else None

    def revoke_session(self, digest, now):
        if self.failure:
            raise AccessStoreError("Store unavailable")
        self.sessions.pop(digest, None)

    def create_attempt(self, attempt, now):
        self.attempts[attempt.state_digest] = attempt

    def consume_attempt(self, digest, binding, now):
        attempt = self.attempts.get(digest)
        if (
            attempt
            and attempt.browser_binding_digest == binding
            and attempt.created_at <= now < attempt.expires_at
        ):
            return self.attempts.pop(digest)
        return None


class Provider:
    def __init__(self, store):
        self.store = store
        self.calls = 0
        self.identity = VerifiedIdentity(
            store.user.identity_issuer, store.user.identity_subject
        )
        self.failure = False

    def authorization_url(self, callback, state, challenge):
        return "https://provider.test/authorize?state=" + state

    def exchange(self, code, verifier, callback):
        assert not self.store.attempts  # atomic consume has already returned
        self.calls += 1
        if self.failure:
            raise UnauthenticatedError("Login failed")
        return self.identity


@pytest.fixture
def lifecycle():
    store, clock, security = Store(), Clock(), RandomSecurityMaterial()
    provider = Provider(store)
    login = LoginService(
        provider,
        store,
        store,
        store,
        security,
        clock,
        callback_uri="https://backend.test/callback",
    )
    return (
        login,
        AccessService(store, security, clock),
        provider,
        store,
        clock,
        security,
    )


def sign_in(lifecycle):
    login = lifecycle[0]
    redirect = login.begin()
    state = parse_qs(urlsplit(redirect.authorization_url).query)["state"][0]
    return login.complete("code", state, redirect.browser_binding)


@pytest.mark.parametrize("role", list(Role))
def test_seeded_personas_current_identity_and_spoofed_role(lifecycle, role):
    _, access, provider, store, _, _ = lifecycle
    store.user = replace(store.user, role=role)
    established = sign_in(lifecycle)
    assert access.current_identity(established.token).user.role == role
    store.user = replace(store.user, role=Role.ANALYST)
    assert access.current_identity(established.token).user.role == Role.ANALYST
    assert provider.calls == 1
    assert "token" not in vars(provider)
    assert established.token not in repr(established)


def test_fixed_expiry_activity_independence_and_logout(lifecycle):
    _, access, provider, _, clock, _ = lifecycle
    first, second = sign_in(lifecycle), sign_in(lifecycle)
    assert first.expires_at == NOW + timedelta(hours=1)
    clock.time = first.expires_at - timedelta(microseconds=1)
    assert access.current_identity(first.token).expires_at == first.expires_at
    access.logout(first.token)
    access.logout(first.token)
    with pytest.raises(UnauthenticatedError):
        access.resolve(first.token)
    assert access.resolve(second.token)
    clock.time = first.expires_at
    with pytest.raises(UnauthenticatedError):
        access.resolve(second.token)
    assert provider.calls == 2


@pytest.mark.parametrize(
    "failure",
    ["binding", "state", "expiry", "provider", "subject", "issuer", "missing", "role"],
)
def test_generic_login_failures_no_session(lifecycle, failure):
    login, _, provider, store, clock, _ = lifecycle
    redirect = login.begin()
    state = parse_qs(urlsplit(redirect.authorization_url).query)["state"][0]
    binding = redirect.browser_binding
    if failure == "binding":
        binding = "wrong"
    elif failure == "state":
        state = "wrong"
    elif failure == "expiry":
        clock.time += timedelta(minutes=10)
    elif failure == "provider":
        provider.failure = True
    elif failure in {"subject", "issuer"}:
        provider.identity = replace(provider.identity, **{failure: "wrong"})
    elif failure == "missing":
        store.user = None
    else:
        store.user = replace(store.user, role="invented")
    with pytest.raises(UnauthenticatedError, match="^Login failed$"):
        login.complete("code", state, binding)
    assert not store.sessions


def test_attempt_replay_and_browser_mismatch(lifecycle):
    login, _, provider, _, _, _ = lifecycle
    redirect = login.begin()
    state = parse_qs(urlsplit(redirect.authorization_url).query)["state"][0]
    with pytest.raises(UnauthenticatedError):
        login.complete("code", state, "wrong")
    assert provider.calls == 0
    login.complete("code", state, redirect.browser_binding)
    with pytest.raises(UnauthenticatedError):
        login.complete("code", state, redirect.browser_binding)
    assert provider.calls == 1


def test_store_failure_denies_and_never_acknowledges_logout(lifecycle):
    _, access, _, store, _, _ = lifecycle
    session = sign_in(lifecycle)
    store.failure = True
    with pytest.raises(AccessStoreError):
        access.resolve(session.token)
    with pytest.raises(AccessStoreError):
        access.logout(session.token)
    store.failure = False
    assert access.resolve(session.token)


def test_security_pkce_csrf_repr_and_redirect_allowlist(lifecycle):
    login, _, _, store, _, security = lifecycle
    a, b = security.random_token(), security.random_token()
    assert len(a) == 43 and a != b and len(security.digest(a)) == 64
    assert (
        security.pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
        == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )
    assert security.verify_csrf(a, security.csrf_token(a))
    assert not security.verify_csrf(b, security.csrf_token(a))
    assert not security.verify_csrf(a, "☃")
    for path in ("https://evil.test", "//evil.test", "/unknown"):
        with pytest.raises(UnauthenticatedError):
            login.begin(path)
    login.begin()
    attempt = next(iter(store.attempts.values()))
    assert attempt.pkce_verifier not in repr(attempt)
