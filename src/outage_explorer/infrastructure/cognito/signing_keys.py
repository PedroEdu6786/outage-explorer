"""Bounded, rotating Cognito signing-key cache."""

import threading
from collections.abc import Callable

import jwt

from outage_explorer.infrastructure.cognito.config import CognitoConfig
from outage_explorer.infrastructure.cognito.jwks import parse_keys
from outage_explorer.infrastructure.cognito.provider_http import ProviderHttpClient


class SigningKeyCache:
    def __init__(
        self,
        config: CognitoConfig,
        client: ProviderHttpClient,
        clock: Callable[[], float],
    ) -> None:
        self._config = config
        self._client = client
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._cached_at = float("-inf")
        self._lock = threading.Lock()

    def get(self, kid: str) -> jwt.PyJWK:
        with self._lock:
            now = self._clock()
            stale = now - self._cached_at >= self._config.cache_seconds
            if stale or (
                kid not in self._keys
                and now - self._cached_at >= self._config.rotation_seconds
            ):
                self._refresh(now)
            return self._keys[kid]

    def _refresh(self, now: float) -> None:
        # Failed retrieval is throttled too, avoiding unknown-kid request storms.
        self._cached_at = now
        self._keys = {}
        document = self._client.request(
            "GET", self._config.issuer + "/.well-known/jwks.json"
        )
        self._keys = parse_keys(document, self._config.max_keys)
