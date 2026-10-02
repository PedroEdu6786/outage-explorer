"""Dedicated startup wrapper; never import this module from a handler."""

from flask import Flask

from outage_explorer.bootstrap import build_http_app


def create_app() -> Flask:
    return build_http_app()
