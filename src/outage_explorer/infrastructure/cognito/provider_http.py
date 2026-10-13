"""Bounded HTTP requests to the Cognito provider."""

import json
from collections.abc import Callable

import httpx

from outage_explorer.infrastructure.cognito.config import CognitoConfig
from outage_explorer.infrastructure.cognito.wire_logging import quiet_provider_wire


class ProviderHttpClient:
    def __init__(
        self,
        config: CognitoConfig,
        *,
        transport: httpx.BaseTransport | None,
        clock: Callable[[], float],
    ) -> None:
        self._config = config
        self._clock = clock
        self._client = httpx.Client(
            transport=transport,
            timeout=config.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self, method: str, url: str, data: dict[str, str] | None = None
    ) -> object:
        with quiet_provider_wire():
            deadline = self._clock() + self._config.timeout_seconds
            try:
                auth = (
                    httpx.BasicAuth(self._config.client_id, self._config.client_secret)
                    if method == "POST" and self._config.client_secret is not None
                    else None
                )
                with self._client.stream(method, url, data=data, auth=auth) as response:
                    return self._read_response(response, deadline)
            finally:
                self._client.cookies.clear()

    def _read_response(self, response: httpx.Response, deadline: float) -> object:
        if response.status_code != 200:
            raise ValueError("Provider failure")
        content = bytearray()
        for chunk in response.iter_bytes(chunk_size=4096):
            if (
                self._clock() >= deadline
                or len(content) + len(chunk) > self._config.max_response_bytes
            ):
                raise ValueError("Provider response bound")
            content.extend(chunk)
        return json.loads(content)
