"""Explicit credential modes reject configuration before any I/O."""

import pytest

from outage_explorer.settings import auth_settings, database_settings
from tests.integration.test_user_access_http import CONFIG

IAM = {
    "OUTAGE_ACCESS_DATABASE_MODE": "iam",
    "OUTAGE_ACCESS_DATABASE_HOST": "database.abc.us-east-1.rds.amazonaws.com",
    "OUTAGE_ACCESS_DATABASE_NAME": "outage",
    "OUTAGE_ACCESS_DATABASE_USER": "outage_app",
    "OUTAGE_ACCESS_DATABASE_REGION": "us-east-1",
    "OUTAGE_ACCESS_DATABASE_PROFILE": "outage-explorer",
    "OUTAGE_ACCESS_DATABASE_SSLROOTCERT": "/trusted/rds.pem",
}


def test_iam_and_confidential_settings_are_secret_free():
    environment = {k: v for k, v in CONFIG.items() if k != "OUTAGE_ACCESS_DATABASE_DSN"}
    settings = auth_settings(
        environment | IAM | {"COGNITO_APP_CLIENT_SECRET": "PRIVATE"}
    )
    assert settings.database.mode == "iam"
    assert settings.database.port == 5432
    assert settings.client_secret == "PRIVATE"
    assert "PRIVATE" not in repr(settings)
    assert "password=" not in settings.database_dsn


@pytest.mark.parametrize(
    "change",
    [
        {"OUTAGE_ACCESS_DATABASE_DSN": "password=SECRET"},
        {"OUTAGE_ACCESS_DATABASE_HOST": "untrusted.test"},
        {"OUTAGE_ACCESS_DATABASE_PORT": "0"},
        {"OUTAGE_ACCESS_DATABASE_REGION": ""},
        {"OUTAGE_ACCESS_DATABASE_USER": "\nSECRET"},
        {"OUTAGE_ACCESS_DATABASE_PROFILE": ""},
        {"OUTAGE_ACCESS_DATABASE_MODE": ""},
    ],
)
def test_invalid_iam_modes_are_sanitized(change):
    with pytest.raises(ValueError, match="^Invalid PostgreSQL configuration$"):
        database_settings(IAM | change)


@pytest.mark.parametrize("mode", ["dsn", "local", "password"])
def test_legacy_explicit_local_password_dsn(mode):
    settings = database_settings(
        {
            "OUTAGE_ACCESS_DATABASE_MODE": mode,
            "OUTAGE_ACCESS_DATABASE_DSN": "host=127.0.0.1 dbname=test password=PRIVATE",
        }
    )
    assert settings.mode == mode and "PRIVATE" not in repr(settings)


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "password=SECRET",
        "host=remote.test sslmode=require",
        "host=localhost hostaddr=remote.test",
    ],
)
def test_invalid_dsn(dsn):
    with pytest.raises(ValueError, match="Invalid PostgreSQL configuration"):
        database_settings({"OUTAGE_ACCESS_DATABASE_DSN": dsn})


def test_setup_configuration_needs_no_provider_and_disabled_http_is_inert():
    assert database_settings(IAM).mode == "iam"
    assert auth_settings({"OUTAGE_AUTH_ENABLED": "false"} | IAM) is None
    assert auth_settings({}) is None


@pytest.mark.parametrize("secret", ["", "\nSECRET", " "])
def test_empty_confidential_secret_is_not_public_fallback(secret):
    with pytest.raises(ValueError, match="Invalid authentication configuration"):
        auth_settings(CONFIG | {"COGNITO_APP_CLIENT_SECRET": secret})
