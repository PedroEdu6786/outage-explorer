"""Standalone controlled auth composition; never uses connector or live AWS."""

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from outage_explorer.application.dto import SeedIdentity
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.health import HealthService
from outage_explorer.application.services.login import LoginService
from outage_explorer.application.services.seed_users import SeedUsers
from outage_explorer.domain.access import Role
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.infrastructure.cognito.identity import (
    CognitoConfig,
    CognitoIdentityProvider,
)
from outage_explorer.infrastructure.postgresql.access import PostgresqlAccessStore
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.security import RandomSecurityMaterial
from tests.integration.test_user_access_postgresql import (
    database as disposable_database,
)

ISSUER = "https://cognito-idp.test/pool"


@pytest.fixture
def database():
    if not os.environ.get("OUTAGE_TEST_POSTGRES_DSN"):
        pytest.fail(
            "Required acceptance setup missing: set OUTAGE_TEST_POSTGRES_DSN to disposable loopback PostgreSQL"
        )
    generator = disposable_database.__wrapped__()
    dsn = next(generator)
    try:
        yield dsn
    finally:
        try:
            next(generator)
        except StopIteration:
            pass


class Clock:
    def __init__(self):
        self.time = datetime.now(UTC).replace(microsecond=0)

    def now(self):
        return self.time


@dataclass
class Harness:
    app: object
    access: AccessService
    store: PostgresqlAccessStore
    pool: BoundedPostgresqlPool
    clock: Clock
    security: RandomSecurityMaterial
    calls: list
    origin: str
    signatures: list


@pytest.fixture
def harness_factory(database):
    resources = []

    def create(origin="http://localhost:8000", *, iam=False):
        signatures = []

        def sign():
            signatures.append(time.monotonic())
            return "CONTROLLED-IAM-" + str(len(signatures))

        pool = BoundedPostgresqlPool(database, password_provider=sign if iam else None)
        store = PostgresqlAccessStore(pool)
        SeedUsers(store).execute(
            tuple(
                SeedIdentity(
                    ISSUER, role.value, role.value + "@test.example", role.value
                )
                for role in Role
            )
        )
        security, clock, calls = RandomSecurityMaterial(), Clock(), []
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        import json

        jwk = dict(
            json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())),
            kid="test",
            alg="RS256",
            use="sig",
        )

        def provider_request(request):
            from urllib.parse import parse_qs

            calls.append(request)
            if request.method == "GET":
                assert "authorization" not in request.headers
                return httpx.Response(200, json={"keys": [jwk]})
            if (
                request.headers.get("authorization")
                != "Basic Y2xpZW50OkNPTkZJREVOVElBTA=="
            ):
                return httpx.Response(401, json={"error": "invalid_client"})
            values = parse_qs(request.content.decode())
            code = values["code"][0]
            if code == "invalid":
                return httpx.Response(400, json={"error": "invalid_grant"})
            token = jwt.encode(
                dict(
                    iss=ISSUER,
                    sub=code,
                    exp=int(time.time()) + 120,
                    token_use="access",
                    client_id="client",
                    role="admin",
                    **{"cognito:groups": ["admin"]},
                ),
                key,
                algorithm="RS256",
                headers={"kid": "test"},
            )
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "access_token": token,
                    "refresh_token": "NEVER-RENEW",
                },
            )

        provider = CognitoIdentityProvider(
            CognitoConfig(
                ISSUER,
                "https://login.test",
                "client",
                ("email",),
                client_secret="CONFIDENTIAL",
            ),
            transport=httpx.MockTransport(provider_request),
        )
        login = LoginService(
            provider,
            store,
            store,
            store,
            security,
            clock,
            callback_uri=origin + "/api/auth/callback",
            allowed_destinations=frozenset({"/"}),
        )
        access = AccessService(store, security, clock)
        transport = AuthTransport(origin, frozenset({origin}), True)
        app = create_app(
            HealthService(clock),
            login_service=login,
            access_service=access,
            auth_transport=transport,
        )
        app.add_url_rule(
            "/",
            "test_index",
            lambda: "<html><body>Controlled authentication harness</body></html>",
        )
        resources.append((provider, pool))
        return Harness(
            app, access, store, pool, clock, security, calls, origin, signatures
        )

    yield create
    for provider, pool in resources:
        provider.close()
        pool.close()


@pytest.fixture
def harness(harness_factory):
    return harness_factory()
