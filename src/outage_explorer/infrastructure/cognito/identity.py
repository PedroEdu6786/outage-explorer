"""Cognito identity adapter coordinating code exchange and token verification."""

import os
import time

import httpx

from outage_explorer.application.dto import VerifiedIdentity
from outage_explorer.application.errors import (
    AccessConfigurationError,
    UnauthenticatedError,
)
from outage_explorer.infrastructure.cognito.access_tokens import AccessTokenVerifier
from outage_explorer.infrastructure.cognito.config import CognitoConfig
from outage_explorer.infrastructure.cognito.oauth import CognitoOAuthClient
from outage_explorer.infrastructure.cognito.provider_http import ProviderHttpClient
from outage_explorer.infrastructure.cognito.signing_keys import SigningKeyCache


class CognitoIdentityProvider:
    def __init__(
        self, config: CognitoConfig, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._owner = os.getpid()
        self._client = ProviderHttpClient(
            config, transport=transport, clock=time.monotonic
        )
        self._oauth = CognitoOAuthClient(config, self._client)
        self._keys = SigningKeyCache(config, self._client, time.monotonic)
        self._tokens = AccessTokenVerifier(config, self._keys.get)

    def close(self) -> None:
        if os.getpid() != self._owner:
            raise AccessConfigurationError("Provider resources cannot cross processes")
        self._client.close()

    def authorization_url(self, callback_uri: str, state: str, challenge: str) -> str:
        return self._oauth.authorization_url(callback_uri, state, challenge)

    def exchange(self, code: str, verifier: str, callback_uri: str) -> VerifiedIdentity:
        try:
            if os.getpid() != self._owner:
                raise ValueError("Provider resources cannot cross processes")
            return self._tokens.verify(
                self._oauth.exchange_access_token(code, verifier, callback_uri)
            )
        except Exception:
            raise UnauthenticatedError("Login failed") from None
