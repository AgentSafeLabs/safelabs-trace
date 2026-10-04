"""Shared test helpers. All strings are synthetic and non-harmful; the salt is a test value."""

from safelabs_trace.schema import EVENT_TYPES

SALT = b"test-salt-canary-0001"


def full_coverage(**over):
    cov = {t: "emitted" for t in EVENT_TYPES}
    cov.update(over)
    return cov
