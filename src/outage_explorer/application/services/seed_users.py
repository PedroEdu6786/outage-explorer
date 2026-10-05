"""Controlled provider linkage; never register or provision accounts."""

from outage_explorer.application.dto import SeedIdentity
from outage_explorer.application.errors import AccessConfigurationError
from outage_explorer.application.ports.access import UserStore
from outage_explorer.domain.access import Role


def validate_identities(identities: tuple[SeedIdentity, ...]) -> None:
    if not identities or len(identities) > 1000:
        raise AccessConfigurationError("Invalid seed manifest")
    keys: set[tuple[str, str]] = set()
    emails: set[str] = set()
    for identity in identities:
        fields = (
            (identity.identity_issuer, 2048),
            (identity.identity_subject, 2048),
            (identity.email, 320),
        )
        if any(
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or len(value) > limit
            for value, limit in fields
        ):
            raise AccessConfigurationError("Invalid seed manifest")
        if "@" not in identity.email or identity.role not in tuple(Role):
            raise AccessConfigurationError("Invalid seed manifest")
        key = (identity.identity_issuer, identity.identity_subject)
        email = identity.email.casefold()
        if key in keys or email in emails:
            raise AccessConfigurationError("Duplicate seed linkage")
        keys.add(key)
        emails.add(email)


class SeedUsers:
    def __init__(self, store: UserStore) -> None:
        self._store = store

    def execute(self, identities: tuple[SeedIdentity, ...]) -> int:
        validate_identities(identities)
        return self._store.seed(identities)
