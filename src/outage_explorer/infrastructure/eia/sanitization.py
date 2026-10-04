"""Bounded JSON sanitization before persistence; paths never include raw keys."""

import json
import math
import re
from dataclasses import dataclass
from urllib.parse import quote, quote_plus

from outage_explorer.application.ports.source import (
    SourceBounds,
    SourceError,
    SourceLimitError,
)

REDACTED = "[REDACTED]"
_CREDENTIAL_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "proxyauthorization",
        "password",
        "passwd",
        "pgpassword",
        "secret",
        "clientsecret",
        "token",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "awsaccesskeyid",
        "awssecretaccesskey",
        "awssessiontoken",
        "cookie",
        "setcookie",
        "credential",
        "credentials",
    }
)
_CREDENTIAL_TEXT = re.compile(
    r"(?i)((?:api[_-]?key|password|client[_-]?secret|access[_-]?token|"
    r"refresh[_-]?token|authorization)\s*[=:]\s*)([^\s&\"'<>]+)"
)


@dataclass(frozen=True)
class Sanitized:
    value: object
    paths: tuple[str, ...]


class Sanitizer:
    def __init__(self, secrets: tuple[str, ...], bounds: SourceBounds) -> None:
        if any(not secret for secret in secrets):
            raise SourceError("Empty configured secret")
        self.bounds = bounds
        self._secrets = tuple(
            sorted(
                {
                    form
                    for secret in secrets
                    for form in (secret, quote(secret, safe=""), quote_plus(secret))
                },
                key=len,
                reverse=True,
            )
        )

    def text(self, value: str) -> str:
        try:
            size = len(value.encode("utf-8"))
        except UnicodeError:
            raise SourceError("Unsupported source text encoding") from None
        if size > self.bounds.field_bytes:
            raise SourceLimitError("Exceeded source field bytes")
        for secret in self._secrets:
            value = value.replace(secret, REDACTED)
        return _CREDENTIAL_TEXT.sub(lambda match: match[1] + REDACTED, value)

    def sanitize(self, value: object) -> Sanitized:
        paths: list[str] = []
        nodes = 0

        def visit(item: object, path: str, depth: int) -> object:
            nonlocal nodes
            nodes += 1
            if nodes > self.bounds.json_nodes or depth > self.bounds.json_depth:
                raise SourceLimitError("Exceeded JSON complexity")
            if isinstance(item, str):
                cleaned_text = self.text(item)
                if cleaned_text != item:
                    paths.append(path)
                return cleaned_text
            if item is None or type(item) in (bool, int):
                return item
            if isinstance(item, float) and math.isfinite(item):
                return item
            if isinstance(item, list):
                return [
                    visit(child, f"{path}/{index}", depth + 1)
                    for index, child in enumerate(item)
                ]
            if isinstance(item, dict):
                result: dict[str, object] = {}
                for index, (key, child) in enumerate(item.items()):
                    if not isinstance(key, str):
                        raise SourceError("JSON keys must be strings")
                    key_path = f"{path}/@{index}"
                    clean_key = visit(key, key_path + "/key", depth + 1)
                    assert isinstance(clean_key, str)
                    cleaned = visit(child, key_path + "/value", depth + 1)
                    if re.sub(r"[^a-z0-9]", "", key.lower()) in _CREDENTIAL_KEYS:
                        cleaned = REDACTED
                        paths.append(key_path + "/value")
                    if clean_key in result:
                        raise SourceError("Sanitized JSON key collision")
                    result[clean_key] = cleaned
                return result
            raise SourceError("Unsupported JSON value")

        return Sanitized(visit(value, "$", 0), tuple(dict.fromkeys(paths)))


def parse_json(body: bytes, bounds: SourceBounds) -> object:
    """Check nesting before the stdlib parser; bytes already capped by transport."""
    depth = 0
    quoted = escaped = False
    for byte in body:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > bounds.json_depth:
                raise SourceLimitError("Exceeded JSON depth")
        elif byte in (93, 125):
            depth -= 1

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise SourceError("Duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(body, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise SourceError("Invalid source JSON") from None
