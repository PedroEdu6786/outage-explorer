"""Local artifact recovery configuration."""

from collections.abc import Mapping
from dataclasses import asdict

from .connector import (
    ArtifactSettings,
    ModelSettings,
    ResourceWorkerSettings,
    _argument,
    _budgets,
    _document,
    resource_worker_settings,
)
from .s3 import S3Settings, s3_settings


def artifact_settings(
    staging: str | None,
    resources: str | None,
    environment: Mapping[str, str],
    config_path: str | None = None,
    s3_workers: int | None = None,
) -> tuple[
    str, str, ArtifactSettings, ModelSettings, S3Settings, ResourceWorkerSettings
]:
    """Exact local identity input; recovery requires no EIA key or source dates."""
    try:
        document = _document(config_path)
        root = _argument(staging, document, "staging")
        if "\x00" in root or not resources or "\x00" in resources:
            raise ValueError
        return (
            root,
            resources,
            ArtifactSettings(
                **_budgets(document.get("artifact", {}), asdict(ArtifactSettings()))
            ),
            ModelSettings(
                **_budgets(document.get("model", {}), asdict(ModelSettings()))
            ),
            s3_settings(environment),
            resource_worker_settings(document, None, s3_workers),
        )
    except (KeyError, ValueError, TypeError, OSError, UnicodeError, RecursionError):
        raise ValueError("Invalid connector artifact configuration") from None
