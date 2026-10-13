"""Verify Cognito access-token signature and identity claims."""

from collections.abc import Callable

import jwt

from outage_explorer.application.dto import VerifiedIdentity
from outage_explorer.infrastructure.cognito.config import CognitoConfig


class AccessTokenVerifier:
    def __init__(
        self, config: CognitoConfig, signing_key: Callable[[str], jwt.PyJWK]
    ) -> None:
        self._config = config
        self._signing_key = signing_key

    def verify(self, token: str) -> VerifiedIdentity:
        kid = self._key_id(token)
        claims = jwt.decode(
            token,
            self._signing_key(kid).key,
            algorithms=["RS256"],
            issuer=self._config.issuer,
            audience=self._config.resource,
            options={
                "require": ["iss", "sub", "exp", "token_use", "client_id"],
                "verify_aud": self._config.resource is not None,
            },
        )
        return VerifiedIdentity(self._config.issuer, self._subject(claims))

    @staticmethod
    def _key_id(token: str) -> str:
        if not isinstance(token, str) or len(token) > 16384:
            raise ValueError("Invalid token")
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if (
            header.get("alg") != "RS256"
            or not isinstance(kid, str)
            or not 1 <= len(kid) <= 256
        ):
            raise ValueError("Invalid signature header")
        return kid

    def _subject(self, claims: dict[str, object]) -> str:
        if (
            claims["token_use"] != "access"
            or claims["client_id"] != self._config.client_id
            or not isinstance(claims["sub"], str)
            or not claims["sub"]
            or len(claims["sub"]) > 2048
        ):
            raise ValueError("Invalid identity")
        return claims["sub"]
