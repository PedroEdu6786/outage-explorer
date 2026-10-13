"""Durable connector target configuration."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class S3Settings:
    bucket: str
    prefix: str
    region: str
    profile: str | None = field(default=None, repr=False)


def s3_settings(environment: Mapping[str, str]) -> S3Settings:
    """Validate the durable target without credentials, source or storage I/O."""
    try:
        bucket, prefix = (
            environment["OUTAGE_S3_BUCKET"],
            environment["OUTAGE_S3_PREFIX"],
        )
        region = environment["AWS_REGION"]
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)
            or not re.fullmatch(r"[A-Za-z0-9_/-]+/", prefix)
            or any(part in (".", "..", "") for part in prefix[:-1].split("/"))
            or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", region)
        ):
            raise ValueError
        profile = environment.get("AWS_PROFILE")
        if profile is not None and (
            not profile.strip() or any(ord(char) < 32 for char in profile)
        ):
            raise ValueError
        return S3Settings(bucket, prefix, region, profile)
    except (KeyError, ValueError, TypeError):
        raise ValueError("Invalid connector S3 configuration") from None
