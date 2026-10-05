"""Cryptographic material; credentials never enter object representations."""

import base64
import hashlib
import hmac
import secrets


class RandomSecurityMaterial:
    def random_token(self) -> str:
        return secrets.token_urlsafe(32)

    def digest(self, token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def pkce_challenge(self, verifier: str) -> str:
        return (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .decode("ascii")
            .rstrip("=")
        )

    def csrf_token(self, session_token: str) -> str:
        return hmac.new(
            session_token.encode("ascii"), b"outage-explorer:csrf:v1", hashlib.sha256
        ).hexdigest()

    def verify_csrf(self, session_token: str, supplied: str) -> bool:
        try:
            return hmac.compare_digest(self.csrf_token(session_token), supplied)
        except (UnicodeError, TypeError):
            return False
