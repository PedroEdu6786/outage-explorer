"""Failures independent of transport status codes."""


class VerificationError(Exception):
    """Invalid evidence, arithmetic invariant, or unsuccessful report write."""
