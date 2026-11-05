"""Blast Radius: coordinate npm supply-chain incident response in Switch rooms."""

from datetime import datetime, timezone

__version__ = "0.1.0"


def utc_now() -> str:
    """Current UTC time as ISO 8601 with a trailing Z, to the second."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
