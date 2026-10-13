"""Bounded RS256 signing-key document validation."""

import jwt


def parse_keys(document: object, max_keys: int) -> dict[str, jwt.PyJWK]:
    if (
        not isinstance(document, dict)
        or not isinstance(document.get("keys"), list)
        or not 1 <= len(document["keys"]) <= max_keys
    ):
        raise ValueError("Invalid keys")
    keys: dict[str, jwt.PyJWK] = {}
    for item in document["keys"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid key")
        if (
            item.get("kty") != "RSA"
            or item.get("alg") != "RS256"
            or item.get("use") != "sig"
        ):
            raise ValueError("Invalid key")
        kid = item.get("kid")
        if not isinstance(kid, str) or not kid or kid in keys:
            raise ValueError("Invalid key")
        keys[kid] = jwt.PyJWK.from_dict(item, algorithm="RS256")
    return keys
