"""Typed local defaults and optional JSON overrides, loaded only at startup.

Bootstrap translates these settings to validated application contracts. Defaults
are bounded contributor allowances, not measured live limits. No dotenv is loaded.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

CONFIG_MAX_BYTES = 64 * 1024


@dataclass(frozen=True)
class SourceSettings:
    interval_days: int = 183
    page_rows: int = 500
    rows: int = 30_000
    pages: int = 100
    requests: int = 200
    attempts: int = 3
    request_bytes: int = 4_000
    response_bytes: int = 1_000_000
    total_bytes: int = 30_000_000
    output_bytes: int = 40_000_000
    json_depth: int = 20
    json_nodes: int = 20_000
    field_bytes: int = 20_000
    elapsed_seconds: int = 1_800
    timeout_seconds: int = 10
    backoff_seconds: int = 1


@dataclass(frozen=True)
class ArtifactSettings:
    batch_rows: int = 100
    row_group_rows: int = 100
    row_group_bytes: int = 1_000_000
    file_bytes: int = 2_000_000
    total_bytes: int = 256_000_000
    objects: int = 10_000
    field_bytes: int = 100_000
    json_depth: int = 25


@dataclass(frozen=True)
class ModelSettings:
    incoming_rows: int = 30_000
    prior_rows: int = 30_000
    output_rows: int = 30_000
    fields_per_row: int = 30
    field_chars: int = 10_000
    coefficient_digits: int = 100
    absolute_exponent: int = 100
    source_index: int = 100_000
    interval_days: int = 183
    reason_occurrences: int = 100_000


@dataclass(frozen=True)
class WorkerSettings:
    endpoint_workers: int = 1
    page_workers: int = 1
    s3_workers: int = 1
    memory_bytes: int = 256_000_000
    temporary_bytes: int = 600_000_000

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError("Worker settings must be positive integers")
        if self.endpoint_workers > 3 or self.page_workers > 3 or self.s3_workers > 3:
            raise ValueError("Worker count cannot exceed three")


@dataclass(frozen=True)
class ConnectorSettings:
    start: date
    end: date
    staging: str
    api_key: str = field(repr=False)
    source: SourceSettings = field(default_factory=SourceSettings)
    artifact: ArtifactSettings = field(default_factory=ArtifactSettings)
    model: ModelSettings = field(default_factory=ModelSettings)
    report_bytes: int = 1_000_000
    prior_digest: str | None = None
    prior_bytes: int | None = None
    workers: WorkerSettings = field(default_factory=WorkerSettings)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _document(path: str | None) -> dict[str, object]:
    if path is None:
        return {}
    config_path = Path(path)
    if not config_path.is_file():
        raise ValueError
    with config_path.open("rb") as stream:
        raw = stream.read(CONFIG_MAX_BYTES + 1)
    if len(raw) > CONFIG_MAX_BYTES:
        raise ValueError
    decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(decoded, dict) or decoded.keys() - {
        "start",
        "end",
        "staging",
        "prior",
        "source",
        "artifact",
        "model",
        "report_bytes",
        "workers",
    }:
        raise ValueError
    for name in ("start", "end", "staging", "prior"):
        if name in decoded and not isinstance(decoded[name], str):
            raise ValueError
    return decoded


def _budgets(value: object, defaults: dict[str, int]) -> dict[str, int]:
    if (
        not isinstance(value, dict)
        or value.keys() - defaults.keys()
        or any(
            not isinstance(key, str) or type(limit) is not int or limit <= 0
            for key, limit in value.items()
        )
    ):
        raise ValueError
    return defaults | value


def _argument(value: str | None, document: dict[str, object], name: str) -> str:
    resolved = value if value is not None else document.get(name)
    if not isinstance(resolved, str) or not resolved.strip():
        raise ValueError
    return resolved


def connector_settings(
    start: str | None,
    end: str | None,
    staging: str | None,
    prior: str | None,
    environment: Mapping[str, str],
    config_path: str | None = None,
    fetch_workers: int | None = None,
    s3_workers: int | None = None,
) -> ConnectorSettings:
    try:
        document = _document(config_path)
        start = _argument(start, document, "start")
        end = _argument(end, document, "end")
        staging = _argument(staging, document, "staging")
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first.isoformat() != start or last.isoformat() != end or first > last:
            raise ValueError
        key = environment["EIA_API_KEY"]
        if (
            not key.strip()
            or len(key) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in key)
        ):
            raise ValueError
        if not staging.strip() or "\x00" in staging or key in staging:
            raise ValueError
        source = SourceSettings(
            **_budgets(document.get("source", {}), asdict(SourceSettings()))
        )
        artifact = ArtifactSettings(
            **_budgets(document.get("artifact", {}), asdict(ArtifactSettings()))
        )
        model = ModelSettings(
            **_budgets(document.get("model", {}), asdict(ModelSettings()))
        )
        defaults = ConnectorSettings(first, last, staging, key)
        report_bytes = document.get("report_bytes", defaults.report_bytes)
        if type(report_bytes) is not int or report_bytes <= 0:
            raise ValueError
        digest = None
        size = None
        if prior is None and "prior" in document:
            prior = _argument(None, document, "prior")
        if prior is not None:
            match = re.fullmatch(r"([0-9a-f]{64}):([1-9][0-9]*)", prior)
            if match is None:
                raise ValueError
            digest, count = match.groups()
            size = int(count)
        return ConnectorSettings(
            first,
            last,
            staging,
            key,
            source,
            artifact,
            model,
            report_bytes,
            digest,
            size,
            worker_settings(document, fetch_workers, s3_workers),
        )
    except (ValueError, TypeError, KeyError, OverflowError, OSError, RecursionError):
        raise ValueError("Invalid connector configuration") from None


@dataclass(frozen=True)
class S3Settings:
    bucket: str
    prefix: str
    region: str
    profile: str | None = field(default=None, repr=False)


def s3_settings(environment: Mapping[str, str]) -> S3Settings:
    """Validate the durable target without credentials, source or storage I/O."""
    try:
        bucket, prefix = (
            environment["OUTAGE_S3_BUCKET"],
            environment["OUTAGE_S3_PREFIX"],
        )
        region = environment["AWS_REGION"]
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)
            or not re.fullmatch(r"[A-Za-z0-9_/-]+/", prefix)
            or any(part in (".", "..", "") for part in prefix[:-1].split("/"))
            or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", region)
        ):
            raise ValueError
        profile = environment.get("AWS_PROFILE")
        if profile is not None and (
            not profile.strip() or any(ord(char) < 32 for char in profile)
        ):
            raise ValueError
        return S3Settings(bucket, prefix, region, profile)
    except (KeyError, ValueError, TypeError):
        raise ValueError("Invalid connector S3 configuration") from None


def artifact_settings(
    staging: str | None,
    manifest: str | None,
    environment: Mapping[str, str],
    config_path: str | None = None,
    s3_workers: int | None = None,
) -> tuple[str, str, int, ArtifactSettings, ModelSettings, S3Settings, WorkerSettings]:
    """Recovery needs no EIA key or dates. Validate before constructing clients."""
    try:
        document = _document(config_path)
        root = _argument(staging, document, "staging")
        if "\x00" in root or manifest is None:
            raise ValueError
        match = re.fullmatch(r"([0-9a-f]{64}):([1-9][0-9]*)", manifest)
        if match is None:
            raise ValueError
        digest, size_text = match.groups()
        size = int(size_text)
        artifact = ArtifactSettings(
            **_budgets(document.get("artifact", {}), asdict(ArtifactSettings()))
        )
        model = ModelSettings(
            **_budgets(document.get("model", {}), asdict(ModelSettings()))
        )
        if size > artifact.file_bytes:
            raise ValueError
        s3 = s3_settings(environment)
        return (
            root,
            digest,
            size,
            artifact,
            model,
            s3,
            worker_settings(document, None, s3_workers),
        )
    except (KeyError, ValueError, TypeError, OSError, UnicodeError, RecursionError):
        raise ValueError("Invalid connector artifact configuration") from None


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
    database: "DatabaseSettings | None" = field(default=None, repr=False)
    client_secret: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class DatabaseSettings:
    """Validated target shared by runtime and explicit setup, without AWS I/O."""

    mode: str
    dsn: str = field(repr=False)
    host: str = ""
    port: int = 5432
    user: str = ""
    region: str = ""
    profile: str | None = field(default=None, repr=False)


def database_settings(environment: Mapping[str, str]) -> DatabaseSettings:
    # The driver parser belongs at the configuration boundary, never in the
    # application/domain. Preserve libpq quoting without hand-parsing secrets.
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    try:
        mode = environment.get("OUTAGE_ACCESS_DATABASE_MODE", "dsn")
        iam_names = (
            "OUTAGE_ACCESS_DATABASE_HOST",
            "OUTAGE_ACCESS_DATABASE_PORT",
            "OUTAGE_ACCESS_DATABASE_NAME",
            "OUTAGE_ACCESS_DATABASE_USER",
            "OUTAGE_ACCESS_DATABASE_REGION",
            "OUTAGE_ACCESS_DATABASE_PROFILE",
            "OUTAGE_ACCESS_DATABASE_SSLROOTCERT",
        )
        if mode not in {"dsn", "local", "password", "iam"}:
            raise ValueError
        if mode != "iam":
            if any(name in environment for name in iam_names):
                raise ValueError
            dsn = environment["OUTAGE_ACCESS_DATABASE_DSN"]
            values = conninfo_to_dict(dsn)
        else:
            if "OUTAGE_ACCESS_DATABASE_DSN" in environment:
                raise ValueError
            host = environment["OUTAGE_ACCESS_DATABASE_HOST"]
            user = environment["OUTAGE_ACCESS_DATABASE_USER"]
            region = environment["OUTAGE_ACCESS_DATABASE_REGION"]
            name = environment["OUTAGE_ACCESS_DATABASE_NAME"]
            root = environment["OUTAGE_ACCESS_DATABASE_SSLROOTCERT"]
            port = int(environment.get("OUTAGE_ACCESS_DATABASE_PORT", "5432"))
            profile = environment.get("OUTAGE_ACCESS_DATABASE_PROFILE")
            if (
                not re.fullmatch(r"[A-Za-z0-9.-]+", host)
                or not host.endswith(".rds.amazonaws.com")
                or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", region)
                or not 1 <= port <= 65535
                or any(
                    not v.strip() or any(ord(c) < 32 for c in v)
                    for v in (user, name, root)
                )
                or (
                    profile is not None
                    and (not profile.strip() or any(ord(c) < 32 for c in profile))
                )
            ):
                raise ValueError
            dsn = make_conninfo(
                host=host,
                port=port,
                user=user,
                dbname=name,
                sslmode="verify-full",
                sslrootcert=root,
            )
            return DatabaseSettings(mode, dsn, host, port, user, region, profile)
        host = str(values.get("host", ""))
        local = host in {"127.0.0.1", "localhost", "::1"} or host.startswith("/")
        if (
            not dsn.strip()
            or not host
            or "," in host
            or "service" in values
            or "hostaddr" in values
            or (not local and values.get("sslmode") != "verify-full")
            or (mode == "local" and not local)
            or (mode == "password" and not values.get("password"))
        ):
            raise ValueError
        return DatabaseSettings(mode, dsn)
    except Exception:
        raise ValueError("Invalid PostgreSQL configuration") from None


def auth_settings(environment: Mapping[str, str]) -> AuthSettings | None:
    """Explicit opt-in: unconfigured HTTP still exposes independent health."""
    from urllib.parse import urlsplit

    enabled = environment.get("OUTAGE_AUTH_ENABLED", "false")
    if enabled not in {"true", "false"}:
        raise ValueError("Invalid authentication configuration")
    if enabled == "false":
        return None
    try:
        required = {
            name: environment[name]
            for name in (
                "COGNITO_ISSUER",
                "COGNITO_DOMAIN",
                "COGNITO_APP_CLIENT_ID",
                "COGNITO_OAUTH_SCOPES",
                "OUTAGE_AUTH_PUBLIC_ORIGIN",
                "OUTAGE_AUTH_CALLBACK_URI",
            )
        }
        if any(
            not value or any(ord(char) < 32 for char in value)
            for value in required.values()
        ):
            raise ValueError
        mode = environment.get("OUTAGE_AUTH_DEVELOPMENT_HTTP", "false")
        if mode not in {"true", "false"}:
            raise ValueError
        public = required["OUTAGE_AUTH_PUBLIC_ORIGIN"]
        ui = environment.get("OUTAGE_AUTH_UI_ORIGIN") or public
        development = mode == "true"
        for origin in (public, ui):
            parsed = urlsplit(origin)
            if (
                parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or not parsed.hostname
                or parsed.path
                or parsed.scheme not in {"https", "http"}
            ):
                raise ValueError
            if development and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError
            if parsed.scheme == "http" and (
                not development
                or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError
            if any(char.isspace() for char in origin):
                raise ValueError
            _ = parsed.port  # validate numeric/range constraints
        if required["OUTAGE_AUTH_CALLBACK_URI"] != public + "/api/auth/callback":
            raise ValueError
        paths = environment.get("OUTAGE_AUTH_RETURN_PATHS", "/").split(",")
        if not paths or any(
            not path.startswith("/")
            or path.startswith("//")
            or any(char in path for char in "\\?#%")
            or any(ord(char) < 32 for char in path)
            for path in paths
        ):
            raise ValueError
        values = [
            int(environment.get(name, str(default)))
            for name, default in (
                ("OUTAGE_AUTH_SESSION_SECONDS", 3600),
                ("OUTAGE_AUTH_ATTEMPT_SECONDS", 600),
                ("OUTAGE_AUTH_ATTEMPT_LIMIT", 1000),
            )
        ]
        if (
            not 1 <= values[0] <= 86400
            or not 1 <= values[1] <= 3600
            or not 1 <= values[2] <= 100000
        ):
            raise ValueError
        scopes = tuple(required["COGNITO_OAUTH_SCOPES"].split())
        if not scopes:
            raise ValueError
        database = database_settings(environment)
        secret = environment.get("COGNITO_APP_CLIENT_SECRET")
        if secret is not None and (
            not secret.strip() or len(secret) > 4096 or any(ord(c) < 32 for c in secret)
        ):
            raise ValueError
        return AuthSettings(
            database.dsn,
            required["COGNITO_ISSUER"],
            required["COGNITO_DOMAIN"],
            required["COGNITO_APP_CLIENT_ID"],
            scopes,
            required["OUTAGE_AUTH_CALLBACK_URI"],
            public,
            ui,
            frozenset(paths),
            development,
            environment.get("COGNITO_RESOURCE") or None,
            session_seconds=values[0],
            attempt_seconds=values[1],
            attempt_limit=values[2],
            database=database,
            client_secret=secret,
        )
    except (KeyError, ValueError, TypeError):
        raise ValueError("Invalid authentication configuration") from None


def worker_settings(
    document: dict[str, object], fetch: int | None, s3: int | None
) -> WorkerSettings:
    values = _budgets(document.get("workers", {}), asdict(WorkerSettings()))
    if fetch is not None:
        values["page_workers"] = fetch
    if s3 is not None:
        values["s3_workers"] = s3
    return WorkerSettings(**values)


@dataclass(frozen=True)
class RefreshSettings:
    """Nonsecret startup snapshot; starting limits are not measured budgets."""

    start_date: date
    end_date: date
    max_interval_days: int = 183
    source_interval_days: int = 183
    model_interval_days: int = 183
    candidate_seconds: int = 1800
    persistence_seconds: int = 1800

    def __post_init__(self) -> None:
        limits = (
            self.max_interval_days,
            self.source_interval_days,
            self.model_interval_days,
            self.candidate_seconds,
            self.persistence_seconds,
        )
        if (
            any(type(value) is not int or value <= 0 for value in limits)
            or self.start_date > self.end_date
            or (self.end_date - self.start_date).days + 1 > min(limits[:3])
            or self.max_interval_days > 183
        ):
            raise ValueError("Invalid refresh configuration")


def refresh_settings(environment: Mapping[str, str]) -> RefreshSettings:
    """Resolve strict ISO dates and coordinated positive budgets at startup."""
    try:
        start = environment["OUTAGE_REFRESH_START_DATE"]
        end = environment["OUTAGE_REFRESH_END_DATE"]
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first.isoformat() != start or last.isoformat() != end:
            raise ValueError
        values = [
            int(environment.get(name, str(default)))
            for name, default in (
                ("OUTAGE_REFRESH_MAX_INTERVAL_DAYS", 183),
                ("OUTAGE_REFRESH_SOURCE_INTERVAL_DAYS", 183),
                ("OUTAGE_REFRESH_MODEL_INTERVAL_DAYS", 183),
                ("OUTAGE_REFRESH_CANDIDATE_SECONDS", 1800),
                ("OUTAGE_REFRESH_PERSISTENCE_SECONDS", 1800),
            )
        ]
        result = RefreshSettings(first, last, *values)
        return result
    except (KeyError, ValueError, TypeError, OverflowError):
        raise ValueError("Invalid refresh configuration") from None


@dataclass(frozen=True)
class DataHttpSettings:
    enabled: bool = False


def data_http_settings(environment: Mapping[str, str]) -> DataHttpSettings:
    value = environment.get("OUTAGE_DATA_HTTP_ENABLED", "false")
    if value not in {"true", "false"}:
        raise ValueError("Invalid data HTTP enablement")
    return DataHttpSettings(value == "true")


@dataclass(frozen=True)
class AnalyticalWorkerSettings:
    """Internal v1 image limits; changes require a new matching image/evidence."""

    preparation_seconds: int = 30
    overall_seconds: int = 40
    execution_seconds: int = 10
    memory_bytes: int = 134_217_728
    temporary_bytes: int = 16_777_216
    output_bytes: int = 1_048_576
    max_cell_bytes: int = 1_048_576
    max_depth: int = 16
    max_nested_items: int = 10_000
    max_columns: int = 100
    max_schema_bytes: int = 65_536

    def __post_init__(self) -> None:
        if any(type(v) is not int or v <= 0 for v in vars(self).values()):
            raise ValueError("Invalid analytical worker limits")
        if self.execution_seconds > 10 or self.output_bytes > 1_048_576:
            raise ValueError("Analytical worker limits exceed accepted caps")
