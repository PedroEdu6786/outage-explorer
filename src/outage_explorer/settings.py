"""Compatibility imports for startup configuration.

New composition code should import the focused module in ``configuration``.
Configuration is parsed only when a loader is called, never at import time.
"""

from outage_explorer.configuration.analytical import (
    AnalyticalWorkerSettings,
    DataHttpSettings,
    data_http_settings,
)
from outage_explorer.configuration.artifact import artifact_settings
from outage_explorer.configuration.auth import AuthSettings, auth_settings
from outage_explorer.configuration.connector import (
    CONFIG_MAX_BYTES,
    ArtifactSettings,
    ConnectorSettings,
    ModelSettings,
    ResourceWorkerSettings,
    SourceSettings,
    WorkerSettings,
    connector_settings,
    resource_worker_settings,
    worker_settings,
)
from outage_explorer.configuration.database import DatabaseSettings, database_settings
from outage_explorer.configuration.refresh import RefreshSettings, refresh_settings
from outage_explorer.configuration.s3 import S3Settings, s3_settings

__all__ = [
    "CONFIG_MAX_BYTES",
    "AnalyticalWorkerSettings",
    "ArtifactSettings",
    "AuthSettings",
    "ConnectorSettings",
    "DataHttpSettings",
    "DatabaseSettings",
    "ModelSettings",
    "RefreshSettings",
    "ResourceWorkerSettings",
    "S3Settings",
    "SourceSettings",
    "WorkerSettings",
    "artifact_settings",
    "auth_settings",
    "connector_settings",
    "data_http_settings",
    "database_settings",
    "refresh_settings",
    "resource_worker_settings",
    "s3_settings",
    "worker_settings",
]
