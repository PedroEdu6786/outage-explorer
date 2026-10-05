"""Fresh bounded IAM signing; credential lookup runs only at connection time."""

import logging
import multiprocessing
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from multiprocessing.connection import Connection

from outage_explorer.application.errors import AccessStoreError


@dataclass(frozen=True)
class IAMTarget:
    host: str
    port: int
    user: str
    region: str
    profile: str | None = field(default=None, repr=False)


def _aws_token(target: IAMTarget) -> str:
    import boto3  # type: ignore[import-untyped]
    from botocore.config import Config  # type: ignore[import-untyped]

    session = boto3.Session(profile_name=target.profile, region_name=target.region)
    client = session.client(
        "rds",
        config=Config(
            connect_timeout=1, read_timeout=1, retries={"total_max_attempts": 1}
        ),
    )
    try:
        return str(
            client.generate_db_auth_token(
                DBHostname=target.host,
                Port=target.port,
                DBUsername=target.user,
                Region=target.region,
            )
        )
    finally:
        client.close()


def _sign_in_child(
    target: IAMTarget, signer: Callable[[IAMTarget], str], sender: Connection
) -> None:
    # No SDK exception or credential representation crosses this boundary.
    logging.disable(logging.CRITICAL)
    try:
        token = signer(target)
        if not isinstance(token, str) or not token or len(token) > 32768:
            raise ValueError
        sender.send((True, token))
    except Exception:
        sender.send((False, ""))
    finally:
        sender.close()


class IAMCredentials:
    """A disposable signing subprocess makes all credential-chain waits bounded.

    No cached connection token, thread, process or SDK session exists at startup.
    The signing subprocess has no application database/session capabilities.
    """

    def __init__(
        self,
        target: IAMTarget,
        *,
        timeout_seconds: float = 3,
        signer: Callable[[IAMTarget], str] = _aws_token,
    ) -> None:
        if not 0 < timeout_seconds <= 10:
            raise ValueError("Invalid credential timeout")
        self._target = target
        self._timeout = timeout_seconds
        self._signer = signer
        self._owner = os.getpid()

    def token(self) -> str:
        if os.getpid() != self._owner:
            raise AccessStoreError("PostgreSQL credentials cannot cross processes")
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_sign_in_child,
            args=(self._target, self._signer, sender),
            daemon=True,
        )
        try:
            process.start()
            sender.close()
            if not receiver.poll(self._timeout):
                raise AccessStoreError("PostgreSQL credentials unavailable")
            success, token = receiver.recv()
            if not success:
                raise AccessStoreError("PostgreSQL credentials unavailable")
            return str(token)
        except Exception:
            raise AccessStoreError("PostgreSQL credentials unavailable") from None
        finally:
            sender.close()
            receiver.close()
            if process.pid is not None:
                process.join(timeout=0.1)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=0.5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=0.5)
                process.close()
