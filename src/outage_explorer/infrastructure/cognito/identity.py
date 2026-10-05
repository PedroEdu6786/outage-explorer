"""Trusted Cognito code exchange and bounded, rotating RS256 verification."""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

import httpx
import jwt

from outage_explorer.application.dto import VerifiedIdentity
from outage_explorer.application.errors import (
    AccessConfigurationError,
    UnauthenticatedError,
)


class _QuietWire(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(_WIRE, "active", False)


_WIRE = threading.local()


@dataclass(frozen=True)
class CognitoConfig:
    issuer: str
    domain: str
    client_id: str
    scopes: tuple[str, ...]
    resource: str | None = None
    timeout_seconds: float = 5.0
    max_response_bytes: int = 65536
    max_keys: int = 10
    cache_seconds: float = 300.0
    rotation_seconds: float = 5.0
    client_secret: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for value in (self.issuer, self.domain):
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or value.endswith("/")
            ):
                raise AccessConfigurationError("Invalid provider configuration")
        if (
            not self.client_id
            or not self.scopes
            or any(not item or " " in item for item in self.scopes)
            or not 0 < self.timeout_seconds <= 30
            or not 1024 <= self.max_response_bytes <= 1048576
            or not 1 <= self.max_keys <= 100
            or not 1 <= self.cache_seconds <= 3600
            or not 1 <= self.rotation_seconds <= self.cache_seconds
            or (
                self.client_secret is not None
                and (
                    not self.client_secret.strip()
                    or len(self.client_secret) > 4096
                    or any(ord(c) < 32 for c in self.client_secret)
                )
            )
        ):
            raise AccessConfigurationError("Invalid provider configuration")


class CognitoIdentityProvider:
    def __init__(
        self, config: CognitoConfig, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._owner = os.getpid()
        self._config = config
        self._client = httpx.Client(
            transport=transport,
            timeout=config.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )
        self._keys: dict[str, jwt.PyJWK] = {}
        self._cached_at = float("-inf")
        self._lock = threading.Lock()

    def close(self) -> None:
        if os.getpid() != self._owner:
            raise AccessConfigurationError("Provider resources cannot cross processes")
        self._client.close()

    def authorization_url(self, callback_uri: str, state: str, challenge: str) -> str:
        return (
            self._config.domain
            + "/oauth2/authorize?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": self._config.client_id,
                    "redirect_uri": callback_uri,
                    "scope": " ".join(self._config.scopes),
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    def _request(
        self, method: str, url: str, data: dict[str, str] | None = None
    ) -> object:
        filters = [
            (logging.getLogger(name), _QuietWire())
            for name in (
                "httpx",
                "httpcore",
                "httpcore.connection",
                "httpcore.http11",
                "httpcore.http2",
            )
        ]
        for logger, quiet in filters:
            logger.addFilter(quiet)
        previous = getattr(_WIRE, "active", False)
        _WIRE.active = True
        deadline = time.monotonic() + self._config.timeout_seconds
        try:
            auth = (
                httpx.BasicAuth(self._config.client_id, self._config.client_secret)
                if method == "POST" and self._config.client_secret is not None
                else None
            )
            with self._client.stream(method, url, data=data, auth=auth) as response:
                if response.status_code != 200:
                    raise ValueError("Provider failure")
                content = bytearray()
                for chunk in response.iter_bytes(chunk_size=4096):
                    if (
                        time.monotonic() >= deadline
                        or len(content) + len(chunk) > self._config.max_response_bytes
                    ):
                        raise ValueError("Provider response bound")
                    content.extend(chunk)
                return json.loads(content)
        finally:
            self._client.cookies.clear()
            _WIRE.active = previous
            for logger, quiet in filters:
                logger.removeFilter(quiet)

    def _key(self, kid: str) -> jwt.PyJWK:
        with self._lock:
            now = time.monotonic()
            stale = now - self._cached_at >= self._config.cache_seconds
            if stale or (
                kid not in self._keys
                and now - self._cached_at >= self._config.rotation_seconds
            ):
                # Failed retrieval is throttled too, avoiding unknown-kid request storms.
                self._cached_at = now
                self._keys = {}
                document = self._request(
                    "GET", self._config.issuer + "/.well-known/jwks.json"
                )
                if (
                    not isinstance(document, dict)
                    or not isinstance(document.get("keys"), list)
                    or not 1 <= len(document["keys"]) <= self._config.max_keys
                ):
                    raise ValueError("Invalid keys")
                keys: dict[str, jwt.PyJWK] = {}
                for item in document["keys"]:
                    if (
                        not isinstance(item, dict)
                        or item.get("kty") != "RSA"
                        or item.get("alg") != "RS256"
                        or item.get("use") != "sig"
                        or not isinstance(item.get("kid"), str)
                        or not item["kid"]
                        or item["kid"] in keys
                    ):
                        raise ValueError("Invalid key")
                    keys[item["kid"]] = jwt.PyJWK.from_dict(item, algorithm="RS256")
                self._keys = keys
            return self._keys[kid]

    def _verify(self, token: str) -> VerifiedIdentity:
        if not isinstance(token, str) or len(token) > 16384:
            raise ValueError("Invalid token")
        header = jwt.get_unverified_header(token)
        if (
            header.get("alg") != "RS256"
            or not isinstance(header.get("kid"), str)
            or not 1 <= len(header["kid"]) <= 256
        ):
            raise ValueError("Invalid signature header")
        claims = jwt.decode(
            token,
            self._key(header["kid"]).key,
            algorithms=["RS256"],
            issuer=self._config.issuer,
            audience=self._config.resource,
            options={
                "require": ["iss", "sub", "exp", "token_use", "client_id"],
                "verify_aud": self._config.resource is not None,
            },
        )
        if (
            claims["token_use"] != "access"
            or claims["client_id"] != self._config.client_id
            or not isinstance(claims["sub"], str)
            or not claims["sub"]
            or len(claims["sub"]) > 2048
        ):
            raise ValueError("Invalid identity")
        return VerifiedIdentity(self._config.issuer, claims["sub"])

    def exchange(self, code: str, verifier: str, callback_uri: str) -> VerifiedIdentity:
        try:
            if os.getpid() != self._owner:
                raise ValueError("Provider resources cannot cross processes")
            response = self._request(
                "POST",
                self._config.domain + "/oauth2/token",
                {
                    "grant_type": "authorization_code",
                    "client_id": self._config.client_id,
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": callback_uri,
                },
            )
            if (
                not isinstance(response, dict)
                or response.get("token_type", "").casefold() != "bearer"
            ):
                raise ValueError("Invalid response")
            token = response.get("access_token")
            if not isinstance(token, str):
                raise ValueError("Invalid response")
            return self._verify(token)
        except Exception:
            raise UnauthenticatedError("Login failed") from None
