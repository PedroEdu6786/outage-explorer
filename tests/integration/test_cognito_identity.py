"""Controlled signing keys and provider transport; no real accounts."""

import json
import logging
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from outage_explorer.application.errors import UnauthenticatedError
from outage_explorer.infrastructure.cognito.identity import (
    CognitoConfig,
    CognitoIdentityProvider,
)

ISSUER = "https://cognito-idp.test/pool"


@pytest.fixture
def keys():
    return [
        rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2)
    ]


def jwk(key, kid):
    return dict(
        json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())),
        kid=kid,
        alg="RS256",
        use="sig",
    )


def token(keys, **changes):
    claims = dict(
        iss=ISSUER,
        sub="seeded-subject",
        exp=int(time.time()) + 60,
        token_use="access",
        client_id="trusted-client",
        **{"cognito:groups": ["admin"], "role": "admin"},
    )
    claims.update(changes)
    return jwt.encode(claims, keys[0], algorithm="RS256", headers={"kid": "first"})


def provider(keys, response, *, resource=None, handler_override=None):
    calls = []

    def handler(request):
        calls.append(request)
        if handler_override:
            return handler_override(request)
        if request.method == "POST":
            return httpx.Response(200, json=response)
        return httpx.Response(200, json={"keys": [jwk(keys[0], "first")]})

    config = CognitoConfig(
        ISSUER, "https://login.test", "trusted-client", ("email",), resource=resource
    )
    return CognitoIdentityProvider(
        config, transport=httpx.MockTransport(handler)
    ), calls


def test_pkce_exchange_verified_subject_and_no_token_retention(keys, caplog):
    secret = token(keys)
    identity, calls = provider(
        keys,
        {
            "access_token": secret,
            "refresh_token": "REFRESH-SECRET",
            "id_token": "ID-SECRET",
            "token_type": "Bearer",
        },
    )
    with caplog.at_level(logging.DEBUG):
        result = identity.exchange(
            "CODE-SECRET", "VERIFIER-SECRET", "https://backend.test/callback"
        )
    assert (result.issuer, result.subject) == (ISSUER, "seeded-subject")
    payload = parse_qs(calls[0].content.decode())
    assert payload["code_verifier"] == ["VERIFIER-SECRET"]
    assert payload["grant_type"] == ["authorization_code"]
    assert len(calls) == 2
    assert not any(
        value in repr(result) + caplog.text + repr(identity.__dict__)
        for value in (
            secret,
            "REFRESH-SECRET",
            "ID-SECRET",
            "CODE-SECRET",
            "VERIFIER-SECRET",
        )
    )
    url = identity.authorization_url(
        "https://backend.test/callback", "state", "challenge"
    )
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"] and query["response_type"] == [
        "code"
    ]
    identity.close()


@pytest.mark.parametrize(
    "change",
    [
        {"token_use": "id"},
        {"iss": "https://evil.test/pool"},
        {"client_id": "wrong"},
        {"exp": int(time.time()) - 1},
        {"sub": ""},
        {"aud": "wrong"},
    ],
)
def test_invalid_claims_generic(keys, change):
    identity, _ = provider(
        keys,
        {"access_token": token(keys, **change), "token_type": "Bearer"},
        resource="expected" if "aud" in change else None,
    )
    with pytest.raises(UnauthenticatedError, match="^Login failed$") as error:
        identity.exchange("secret", "secret", "https://callback.test")
    assert error.value.__cause__ is None
    identity.close()


@pytest.mark.parametrize("bad", ["signature", "algorithm", "malformed", "purpose"])
def test_invalid_signature_algorithm_and_response(keys, bad):
    secret = token(keys)
    if bad == "signature":
        secret = jwt.encode(
            dict(
                iss=ISSUER,
                sub="subject",
                exp=int(time.time()) + 60,
                token_use="access",
                client_id="trusted-client",
            ),
            keys[1],
            algorithm="RS256",
            headers={"kid": "first"},
        )
    elif bad == "algorithm":
        secret = jwt.encode(
            {"sub": "subject"}, "a" * 32, algorithm="HS256", headers={"kid": "first"}
        )
    elif bad == "malformed":
        secret = "SECRET-MALFORMED"
    response = (
        {"access_token": secret, "token_type": "Bearer"}
        if bad != "purpose"
        else {"id_token": secret, "token_type": "Bearer"}
    )
    identity, _ = provider(keys, response)
    with pytest.raises(UnauthenticatedError, match="^Login failed$"):
        identity.exchange("code", "verifier", "https://callback.test")
    identity.close()


def test_key_cache_rotation_and_unknown_key_throttle(keys, monkeypatch):
    now = [10.0]
    monkeypatch.setattr(
        "outage_explorer.infrastructure.cognito.identity.time.monotonic", lambda: now[0]
    )
    current = [0]
    count = [0]

    def handler(request):
        if request.method == "GET":
            count[0] += 1
            return httpx.Response(
                200,
                json={"keys": [jwk(keys[current[0]], ("first", "second")[current[0]])]},
            )
        value = (
            token(keys)
            if current[0] == 0
            else jwt.encode(
                dict(
                    iss=ISSUER,
                    sub="rotated",
                    exp=int(time.time()) + 60,
                    token_use="access",
                    client_id="trusted-client",
                ),
                keys[1],
                algorithm="RS256",
                headers={"kid": "second"},
            )
        )
        return httpx.Response(200, json={"access_token": value, "token_type": "Bearer"})

    identity, _ = provider(keys, {}, handler_override=handler)
    identity.exchange("code", "verifier", "https://callback.test")
    identity.exchange("code", "verifier", "https://callback.test")
    assert count[0] == 1
    current[0] = 1
    with pytest.raises(UnauthenticatedError):
        identity.exchange("code", "verifier", "https://callback.test")
    assert count[0] == 1
    now[0] += 5
    assert (
        identity.exchange("code", "verifier", "https://callback.test").subject
        == "rotated"
    )
    assert count[0] == 2
    identity.close()


@pytest.mark.parametrize(
    "failure", ["oversize", "status", "redirect", "timeout", "json", "keys"]
)
def test_bounded_transport_and_sanitized_failures(keys, failure, caplog):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("PROVIDER-SECRET", request=request)
        if failure == "keys" and request.method == "POST":
            return httpx.Response(
                200, json={"access_token": token(keys), "token_type": "Bearer"}
            )
        if failure == "keys":
            return httpx.Response(
                200, json={"keys": [jwk(keys[0], str(index)) for index in range(11)]}
            )
        if failure == "oversize":
            return httpx.Response(200, content=b"x" * 65537)
        if failure == "status":
            return httpx.Response(400, text="PROVIDER-SECRET")
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://evil.test"})
        return httpx.Response(200, content=b"PROVIDER-SECRET")

    identity, calls = provider(keys, {}, handler_override=handler)
    with caplog.at_level(logging.DEBUG), pytest.raises(UnauthenticatedError) as error:
        identity.exchange("CODE-SECRET", "VERIFIER-SECRET", "https://callback.test")
    assert str(error.value) == "Login failed"
    assert "PROVIDER-SECRET" not in caplog.text + str(error.value)
    assert len(calls) <= 2
    identity.close()


@pytest.mark.parametrize(
    "secret, valid", [(None, True), ("CONFIDENTIAL", True), ("INCORRECT", False)]
)
def test_confidential_basic_pkce_without_fallback_or_leak(keys, caplog, secret, valid):
    import base64

    calls = []
    expected = "Basic " + base64.b64encode(b"trusted-client:CONFIDENTIAL").decode()

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"keys": [jwk(keys[0], "first")]})
        if secret is not None and request.headers.get("authorization") != expected:
            return httpx.Response(401, json={"error": "invalid_client"})
        return httpx.Response(
            200,
            json={
                "access_token": token(keys),
                "token_type": "Bearer",
                "refresh_token": "REFRESH-PRIVATE",
            },
        )

    config = CognitoConfig(
        ISSUER, "https://login.test", "trusted-client", ("email",), client_secret=secret
    )
    adapter = CognitoIdentityProvider(config, transport=httpx.MockTransport(handler))
    with caplog.at_level(logging.DEBUG):
        if valid:
            assert (
                adapter.exchange(
                    "CODE-PRIVATE", "PKCE-PRIVATE", "https://backend.test/callback"
                ).subject
                == "seeded-subject"
            )
        else:
            with pytest.raises(UnauthenticatedError, match="^Login failed$"):
                adapter.exchange(
                    "CODE-PRIVATE", "PKCE-PRIVATE", "https://backend.test/callback"
                )
    assert len([call for call in calls if call.method == "POST"]) == 1
    assert parse_qs(calls[0].content.decode())["code_verifier"] == ["PKCE-PRIVATE"]
    if secret is None:
        assert "authorization" not in calls[0].headers
    else:
        assert calls[0].headers["authorization"].startswith("Basic ")
    surface = (
        repr(config)
        + repr(adapter.__dict__)
        + caplog.text
        + adapter.authorization_url(
            "https://backend.test/callback", "state", "challenge"
        )
    )
    assert not any(
        value in surface
        for value in (
            "CONFIDENTIAL",
            "INCORRECT",
            "REFRESH-PRIVATE",
            "CODE-PRIVATE",
            "PKCE-PRIVATE",
            expected,
        )
    )
    adapter.close()
