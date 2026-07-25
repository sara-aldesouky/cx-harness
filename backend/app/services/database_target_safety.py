"""Credential-free classification for operator database safety checks."""

from dataclasses import dataclass
from enum import Enum

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class DatabaseTargetClassification(str, Enum):
    LOCAL_TEST = "Local Test"
    LOCAL_DEVELOPMENT = "Local Development"
    PRODUCTION = "Production"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class DatabaseTarget:
    """Sanitized database identity safe for operator output."""

    host: str
    database: str
    environment: str
    classification: DatabaseTargetClassification


LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
PRODUCTION_HOST_SUFFIXES = (
    "render.com",
    "amazonaws.com",
    "neon.tech",
    "supabase.co",
    "railway.app",
)
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})


def classify_database_target(database_url: str, environment: str) -> DatabaseTarget:
    """Classify a URL while discarding its username, password, and query data."""

    normalized_environment = (environment or "unknown").strip() or "unknown"
    try:
        parsed = make_url(database_url)
        host = (parsed.host or "unknown").lower()
        database = parsed.database or "unknown"
    except (ArgumentError, TypeError, ValueError):
        host = "unknown"
        database = "unknown"

    environment_key = normalized_environment.casefold()
    database_key = database.casefold()
    if environment_key in PRODUCTION_ENVIRONMENTS:
        classification = DatabaseTargetClassification.PRODUCTION
    elif host in LOCAL_HOSTS and "test" in database_key:
        classification = DatabaseTargetClassification.LOCAL_TEST
    elif host in LOCAL_HOSTS:
        classification = DatabaseTargetClassification.LOCAL_DEVELOPMENT
    elif any(host == suffix or host.endswith(f".{suffix}") for suffix in PRODUCTION_HOST_SUFFIXES):
        classification = DatabaseTargetClassification.PRODUCTION
    else:
        classification = DatabaseTargetClassification.UNKNOWN

    return DatabaseTarget(
        host=host,
        database=database,
        environment=normalized_environment,
        classification=classification,
    )
