"""Separate nonsecret parser profile and matching explicit review; no numeric defaults."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.infrastructure.sql_validation.subprocess_inspection import (
    InspectionBounds,
    SubprocessSqlInspector,
)
from outage_explorer.infrastructure.sql_validation.subprocess_protocol import (
    unique_object,
)


def digest(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


@dataclass(frozen=True)
class InspectionProfile:
    bounds: InspectionBounds
    python: str
    prlimit: str
    setpriv: str
    ownership_root: str
    python_sha256: str
    prlimit_sha256: str
    setpriv_sha256: str

    def __post_init__(self) -> None:
        if type(self.bounds) is not InspectionBounds:
            raise ValueError("Explicit parser bounds required")
        for path in (self.python, self.prlimit, self.setpriv, self.ownership_root):
            if (
                not isinstance(path, str)
                or not path.startswith("/")
                or len(path) > 4096
                or any(c in path for c in ("\x00", "\n"))
                or ".." in Path(path).parts
                or str(Path(path)) != path
            ):
                raise ValueError("Explicit canonical parser paths required")
        if not all(
            digest(d)
            for d in (self.python_sha256, self.prlimit_sha256, self.setpriv_sha256)
        ):
            raise ValueError("Parser executable digests required")

    @property
    def identity(self) -> str:
        raw = json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        return hashlib.sha256(raw).hexdigest()

    def build(self) -> SubprocessSqlInspector:
        return SubprocessSqlInspector(
            self.bounds,
            python=self.python,
            prlimit=self.prlimit,
            setpriv=self.setpriv,
            ownership_root=Path(self.ownership_root),
            executable_hashes=(
                self.python_sha256,
                self.prlimit_sha256,
                self.setpriv_sha256,
            ),
        )


@dataclass(frozen=True)
class InspectionReview:
    profile_identity: str
    controlled_report: str
    native_report: str
    reviewer: str
    reviewed_on: date

    def __post_init__(self) -> None:
        if (
            not all(
                digest(d)
                for d in (
                    self.profile_identity,
                    self.controlled_report,
                    self.native_report,
                )
            )
            or type(self.reviewed_on) is not date
            or not isinstance(self.reviewer, str)
            or not self.reviewer
            or len(self.reviewer) > 256
        ):
            raise ValueError("Explicit parser review required")

    def require_ready(self, profile: InspectionProfile) -> None:
        if self.profile_identity != profile.identity:
            raise RuntimeUnavailableError("Reviewed SQL inspection unavailable")


def read_inspection_config(
    path: Path,
) -> tuple[InspectionProfile, InspectionReview | None]:
    with path.open("rb") as stream:
        raw = stream.read(65537)
    try:
        if len(raw) > 65536:
            raise ValueError
        document = json.loads(raw, object_pairs_hook=unique_object)
        if not isinstance(document, dict) or set(document) != {"profile", "evidence"}:
            raise ValueError
        values = document["profile"]
        if not isinstance(values, dict):
            raise ValueError
        values = dict(values)
        values["bounds"] = InspectionBounds(**values["bounds"])
        profile = InspectionProfile(**values)
        evidence = document["evidence"]
        if evidence is None:
            return profile, None
        if not isinstance(evidence, dict):
            raise ValueError
        evidence = dict(evidence)
        evidence["reviewed_on"] = date.fromisoformat(evidence["reviewed_on"])
        return profile, InspectionReview(**evidence)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ValueError("Invalid nonsecret SQL inspection configuration") from None
