"""PostgreSQL connection target configuration."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DatabaseSettings:
    """Validated target shared by runtime and explicit setup, without AWS I/O."""

    mode: str
    dsn: str = field(repr=False)
    host: str = ""
    port: int = 5432
    user: str = ""
    region: str = ""
    profile: str | None = field(default=None, repr=False)


def database_settings(environment: Mapping[str, str]) -> DatabaseSettings:
    # The driver parser belongs at the configuration boundary, never in the
    # application/domain. Preserve libpq quoting without hand-parsing secrets.
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    try:
        mode = environment.get("OUTAGE_ACCESS_DATABASE_MODE", "dsn")
        iam_names = (
            "OUTAGE_ACCESS_DATABASE_HOST",
            "OUTAGE_ACCESS_DATABASE_PORT",
            "OUTAGE_ACCESS_DATABASE_NAME",
            "OUTAGE_ACCESS_DATABASE_USER",
            "OUTAGE_ACCESS_DATABASE_REGION",
            "OUTAGE_ACCESS_DATABASE_PROFILE",
            "OUTAGE_ACCESS_DATABASE_SSLROOTCERT",
        )
        if mode not in {"dsn", "local", "password", "iam"}:
            raise ValueError
        if mode != "iam":
            if any(name in environment for name in iam_names):
                raise ValueError
            dsn = environment["OUTAGE_ACCESS_DATABASE_DSN"]
            values = conninfo_to_dict(dsn)
        else:
            if "OUTAGE_ACCESS_DATABASE_DSN" in environment:
                raise ValueError
            host = environment["OUTAGE_ACCESS_DATABASE_HOST"]
            user = environment["OUTAGE_ACCESS_DATABASE_USER"]
            region = environment["OUTAGE_ACCESS_DATABASE_REGION"]
            name = environment["OUTAGE_ACCESS_DATABASE_NAME"]
            root = environment["OUTAGE_ACCESS_DATABASE_SSLROOTCERT"]
            port = int(environment.get("OUTAGE_ACCESS_DATABASE_PORT", "5432"))
            profile = environment.get("OUTAGE_ACCESS_DATABASE_PROFILE")
            if (
                not re.fullmatch(r"[A-Za-z0-9.-]+", host)
                or not host.endswith(".rds.amazonaws.com")
                or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", region)
                or not 1 <= port <= 65535
                or any(
                    not v.strip() or any(ord(c) < 32 for c in v)
                    for v in (user, name, root)
                )
                or (
                    profile is not None
                    and (not profile.strip() or any(ord(c) < 32 for c in profile))
                )
            ):
                raise ValueError
            dsn = make_conninfo(
                host=host,
                port=port,
                user=user,
                dbname=name,
                sslmode="verify-full",
                sslrootcert=root,
            )
            return DatabaseSettings(mode, dsn, host, port, user, region, profile)
        host = str(values.get("host", ""))
        local = host in {"127.0.0.1", "localhost", "::1"} or host.startswith("/")
        if (
            not dsn.strip()
            or not host
            or "," in host
            or "service" in values
            or "hostaddr" in values
            or (not local and values.get("sslmode") != "verify-full")
            or (mode == "local" and not local)
            or (mode == "password" and not values.get("password"))
        ):
            raise ValueError
        return DatabaseSettings(mode, dsn)
    except Exception:
        raise ValueError("Invalid PostgreSQL configuration") from None
