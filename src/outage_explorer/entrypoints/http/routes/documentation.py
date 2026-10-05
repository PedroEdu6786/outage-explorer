"""Serve the packaged HTTP contract and local Swagger UI assets."""

import json
from typing import cast

from flask import Blueprint, Flask, Response, jsonify
from flask_swagger_ui import get_swaggerui_blueprint  # type: ignore[import-untyped]


def register_documentation(app: Flask, *, development_http: bool = False) -> None:
    blueprint = Blueprint("documentation", __name__)

    @blueprint.get("/api/openapi.json")
    def openapi() -> Response:
        with blueprint.open_resource("../openapi.json") as resource:
            contract = json.load(resource)
        if development_http:
            contract["components"]["securitySchemes"]["SessionCookie"]["name"] = (
                "outage_session"
            )
            for parameter in contract["paths"]["/api/auth/callback"]["get"][
                "parameters"
            ]:
                if parameter["in"] == "cookie":
                    parameter["name"] = "outage_login"
        response = jsonify(contract)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.register_blueprint(blueprint)
    app.register_blueprint(
        cast(
            Blueprint,
            get_swaggerui_blueprint(
                "/api/docs",
                "/api/openapi.json",
                config={
                    "app_name": "Outage Explorer API",
                    "validatorUrl": None,
                    "withCredentials": True,
                },
            ),
        )
    )
