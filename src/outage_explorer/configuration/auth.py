"""Cognito and HTTP session configuration."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .database import DatabaseSettings, database_settings


@dataclass(frozen=True)
class AuthSettings:
    database_dsn: str = field(repr=False)
    issuer: str
    provider_domain: str
    client_id: str
    scopes: tuple[str, ...]
    callback_uri: str
    public_origin: str
    ui_origin: str
    return_paths: frozenset[str]
    development_http: bool = False
    resource: str | None = None
    session_seconds: int = 3600
    attempt_seconds: int = 600
    attempt_limit: int = 1000
    database: DatabaseSettings | None = field(default=None, repr=False)
    client_secret: str | None = field(default=None, repr=False)


_REQUIRED_FIELDS = (
    "COGNITO_ISSUER",
    "COGNITO_DOMAIN",
    "COGNITO_APP_CLIENT_ID",
    "COGNITO_OAUTH_SCOPES",
    "OUTAGE_AUTH_PUBLIC_ORIGIN",
    "OUTAGE_AUTH_CALLBACK_URI",
)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _required_values(environment: Mapping[str, str]) -> dict[str, str]:
    values = {name: environment[name] for name in _REQUIRED_FIELDS}
    if any(
        not value or any(ord(char) < 32 for char in value) for value in values.values()
    ):
        raise ValueError
    return values


def _development_http(environment: Mapping[str, str]) -> bool:
    value = environment.get("OUTAGE_AUTH_DEVELOPMENT_HTTP", "false")
    if value not in {"true", "false"}:
        raise ValueError
    return value == "true"


def _validate_origin(origin: str, development_http: bool) -> None:
    parsed = urlsplit(origin)
    if parsed.username or parsed.password:
        raise ValueError
    if parsed.path or parsed.query or parsed.fragment:
        raise ValueError
    if not parsed.hostname or parsed.scheme not in {"https", "http"}:
        raise ValueError
    if any(char.isspace() for char in origin):
        raise ValueError
    if development_http and parsed.hostname not in _LOCAL_HOSTS:
        raise ValueError
    if parsed.scheme == "http" and (
        not development_http or parsed.hostname not in _LOCAL_HOSTS
    ):
        raise ValueError
    _ = parsed.port  # Validate numeric and range constraints.


def _return_paths(environment: Mapping[str, str]) -> frozenset[str]:
    paths = environment.get("OUTAGE_AUTH_RETURN_PATHS", "/").split(",")
    if not paths or any(
        not path.startswith("/")
        or path.startswith("//")
        or any(char in path for char in "\\?#%")
        or any(ord(char) < 32 for char in path)
        for path in paths
    ):
        raise ValueError
    return frozenset(paths)


def _session_limits(environment: Mapping[str, str]) -> tuple[int, int, int]:
    session_seconds = int(environment.get("OUTAGE_AUTH_SESSION_SECONDS", "3600"))
    attempt_seconds = int(environment.get("OUTAGE_AUTH_ATTEMPT_SECONDS", "600"))
    attempt_limit = int(environment.get("OUTAGE_AUTH_ATTEMPT_LIMIT", "1000"))
    if (
        not 1 <= session_seconds <= 86400
        or not 1 <= attempt_seconds <= 3600
        or not 1 <= attempt_limit <= 100000
    ):
        raise ValueError
    return session_seconds, attempt_seconds, attempt_limit


def _client_secret(environment: Mapping[str, str]) -> str | None:
    secret = environment.get("COGNITO_APP_CLIENT_SECRET")
    if secret is not None and (
        not secret.strip() or len(secret) > 4096 or any(ord(c) < 32 for c in secret)
    ):
        raise ValueError
    return secret


def auth_settings(environment: Mapping[str, str]) -> AuthSettings | None:
    """Explicit opt-in: unconfigured HTTP still exposes independent health."""
    enabled = environment.get("OUTAGE_AUTH_ENABLED", "false")
    if enabled not in {"true", "false"}:
        raise ValueError("Invalid authentication configuration")
    if enabled == "false":
        return None
    try:
        required = _required_values(environment)
        public = required["OUTAGE_AUTH_PUBLIC_ORIGIN"]
        ui = environment.get("OUTAGE_AUTH_UI_ORIGIN") or public
        development = _development_http(environment)
        for origin in (public, ui):
            _validate_origin(origin, development)
        if required["OUTAGE_AUTH_CALLBACK_URI"] != public + "/api/auth/callback":
            raise ValueError
        paths = _return_paths(environment)
        session_seconds, attempt_seconds, attempt_limit = _session_limits(environment)
        scopes = tuple(required["COGNITO_OAUTH_SCOPES"].split())
        if not scopes:
            raise ValueError
        database = database_settings(environment)
        secret = _client_secret(environment)
        return AuthSettings(
            database_dsn=database.dsn,
            issuer=required["COGNITO_ISSUER"],
            provider_domain=required["COGNITO_DOMAIN"],
            client_id=required["COGNITO_APP_CLIENT_ID"],
            scopes=scopes,
            callback_uri=required["OUTAGE_AUTH_CALLBACK_URI"],
            public_origin=public,
            ui_origin=ui,
            return_paths=paths,
            development_http=development,
            resource=environment.get("COGNITO_RESOURCE") or None,
            session_seconds=session_seconds,
            attempt_seconds=attempt_seconds,
            attempt_limit=attempt_limit,
            database=database,
            client_secret=secret,
        )
    except (KeyError, ValueError, TypeError):
        raise ValueError("Invalid authentication configuration") from None
