"""Central preflight dispatch using explicit endpoint policies."""

from collections.abc import Mapping
from dataclasses import dataclass

from flask import Flask, Response, request

from outage_explorer.entrypoints.http.transport.auth import AuthTransport


@dataclass(frozen=True)
class PreflightPolicy:
    methods: frozenset[str]
    allow_idempotency_key: bool = False


PREFLIGHT_POLICIES = {
    "access.login": PreflightPolicy(frozenset({"GET", "POST"})),
    "access.callback": PreflightPolicy(frozenset({"GET", "POST"})),
    "access.session": PreflightPolicy(frozenset({"GET", "POST"})),
    "access.logout": PreflightPolicy(frozenset({"GET", "POST"})),
    "datasets.catalog": PreflightPolicy(frozenset({"GET"})),
    "datasets.preview": PreflightPolicy(frozenset({"GET"})),
    "queries.execute": PreflightPolicy(frozenset({"GET", "POST"})),
    "queries.page": PreflightPolicy(frozenset({"GET", "POST"})),
    "refresh.admit": PreflightPolicy(frozenset({"POST"}), allow_idempotency_key=True),
    "refresh.latest": PreflightPolicy(frozenset({"GET"}), allow_idempotency_key=True),
    "refresh.status": PreflightPolicy(frozenset({"GET"}), allow_idempotency_key=True),
}


def register_preflight_handler(
    app: Flask,
    transport: AuthTransport,
    policies: Mapping[str, PreflightPolicy],
) -> None:
    configured = dict(policies)

    @app.before_request
    def preflight() -> Response | None:
        if request.method != "OPTIONS" or request.endpoint is None:
            return None
        policy = configured.get(request.endpoint)
        if policy is None:
            return None
        return transport.preflight(
            methods=set(policy.methods), idempotency=policy.allow_idempotency_key
        )
