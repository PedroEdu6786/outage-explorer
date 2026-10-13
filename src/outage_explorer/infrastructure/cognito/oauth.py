"""Cognito authorization and token endpoint requests."""

from urllib.parse import urlencode

from outage_explorer.infrastructure.cognito.config import CognitoConfig
from outage_explorer.infrastructure.cognito.provider_http import ProviderHttpClient


class CognitoOAuthClient:
    def __init__(self, config: CognitoConfig, client: ProviderHttpClient) -> None:
        self._config = config
        self._client = client

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

    def exchange_access_token(self, code: str, verifier: str, callback_uri: str) -> str:
        response = self._client.request(
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
        return token
