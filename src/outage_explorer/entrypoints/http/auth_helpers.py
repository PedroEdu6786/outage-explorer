"""Injected HTTP guards; protected use cases must still authorize freshly.

Guards pass named values explicitly, never via Flask globals. Compose guards
outside request validation when authentication/origin must precede parsing.
"""

from collections.abc import Callable
from functools import wraps

from flask import Response

from outage_explorer.application.errors import UnauthenticatedError
from outage_explorer.application.services.access import AccessService
from outage_explorer.entrypoints.http.auth_transport import AuthTransport

Handler = Callable[..., Response]


def authenticated(
    access: AccessService, transport: AuthTransport
) -> Callable[[Handler], Handler]:
    """Inject credential and identity, without granting analytical access."""

    def decorate(handler: Handler) -> Handler:
        @wraps(handler)
        def guarded(*args: object, **kwargs: object) -> Response:
            credential = transport.credential()
            identity = access.current_identity(credential)
            kwargs.update(credential=credential, identity=identity)
            return handler(*args, **kwargs)

        return guarded

    return decorate


def csrf_protected(
    access: AccessService,
    transport: AuthTransport,
    *,
    allow_invalid_session: bool = False,
) -> Callable[[Handler], Handler]:
    """Inject credential and CSRF outcome after exact-origin validation.

    Only idempotent logout opts into invalid-session handling. Store failures and
    invalid CSRF for a live session always propagate before handler work.
    """

    def decorate(handler: Handler) -> Handler:
        @wraps(handler)
        def guarded(*args: object, **kwargs: object) -> Response:
            csrf = transport.mutation_csrf()
            credential = transport.credential()
            validated = True
            try:
                access.validate_csrf(credential, csrf)
            except UnauthenticatedError:
                if not allow_invalid_session:
                    raise
                validated = False
            kwargs.update(credential=credential, csrf_validated=validated)
            return handler(*args, **kwargs)

        return guarded

    return decorate


def validated_request[Validated](
    parser: Callable[[], Validated],
) -> Callable[[Handler], Handler]:
    """Inject a plain schema result as validated; parsing cannot authorize."""

    def decorate(handler: Handler) -> Handler:
        @wraps(handler)
        def guarded(*args: object, **kwargs: object) -> Response:
            kwargs["validated"] = parser()
            return handler(*args, **kwargs)

        return guarded

    return decorate
