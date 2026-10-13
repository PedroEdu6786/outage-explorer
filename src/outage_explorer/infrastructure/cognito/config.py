"""Validated, secret-safe Cognito provider settings."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from outage_explorer.application.errors import AccessConfigurationError


def _trusted_https_endpoint(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    return not (parsed.query or parsed.fragment or value.endswith("/"))


def _valid_client_secret(secret: str | None) -> bool:
    return secret is None or (
        bool(secret.strip())
        and len(secret) <= 4096
        and all(ord(char) >= 32 for char in secret)
    )


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
        if not all(
            _trusted_https_endpoint(value) for value in (self.issuer, self.domain)
        ):
            raise AccessConfigurationError("Invalid provider configuration")
        if not self.client_id or not self.scopes:
            raise AccessConfigurationError("Invalid provider configuration")
        if any(not scope or " " in scope for scope in self.scopes):
            raise AccessConfigurationError("Invalid provider configuration")
        if not 0 < self.timeout_seconds <= 30:
            raise AccessConfigurationError("Invalid provider configuration")
        if not 1024 <= self.max_response_bytes <= 1048576:
            raise AccessConfigurationError("Invalid provider configuration")
        if not 1 <= self.max_keys <= 100:
            raise AccessConfigurationError("Invalid provider configuration")
        if not 1 <= self.cache_seconds <= 3600:
            raise AccessConfigurationError("Invalid provider configuration")
        if not 1 <= self.rotation_seconds <= self.cache_seconds:
            raise AccessConfigurationError("Invalid provider configuration")
        if not _valid_client_secret(self.client_secret):
            raise AccessConfigurationError("Invalid provider configuration")
