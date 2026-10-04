"""Typed local defaults and optional JSON overrides, loaded only at startup.

Bootstrap translates these settings to validated application contracts. Defaults
are initial conservative limits, not measured live limits. No dotenv is loaded.
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
    interval_days: int = 30
    page_rows: int = 2
    rows: int = 10_000
    pages: int = 100
    requests: int = 200
    attempts: int = 1
    request_bytes: int = 4_000
    response_bytes: int = 100_000
    total_bytes: int = 1_000_000
    output_bytes: int = 5_000_000
    json_depth: int = 20
    json_nodes: int = 20_000
    field_bytes: int = 20_000
    elapsed_seconds: int = 60
    timeout_seconds: int = 3
    backoff_seconds: int = 1


@dataclass(frozen=True)
class ArtifactSettings:
    batch_rows: int = 100
    row_group_rows: int = 100
    row_group_bytes: int = 1_000_000
    file_bytes: int = 2_000_000
    total_bytes: int = 100_000_000
    objects: int = 10_000
    field_bytes: int = 100_000
    json_depth: int = 25


@dataclass(frozen=True)
class ModelSettings:
    incoming_rows: int = 10_000
    prior_rows: int = 10_000
    output_rows: int = 10_000
    fields_per_row: int = 30
    field_chars: int = 10_000
    coefficient_digits: int = 100
    absolute_exponent: int = 100
    source_index: int = 100_000
    interval_days: int = 30
    reason_occurrences: int = 100_000


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
        )
    except (ValueError, TypeError, KeyError, OverflowError, OSError, RecursionError):
        raise ValueError("Invalid connector configuration") from None
