"""Unit tests for credential-free database target classification."""

import pytest

from app.services import DatabaseTargetClassification, classify_database_target


@pytest.mark.parametrize(
    "url,environment,expected",
    [
        (
            "postgresql://user:secret@127.0.0.1:5433/cx_harness_test",
            "test",
            DatabaseTargetClassification.LOCAL_TEST,
        ),
        (
            "postgresql://user:secret@localhost:5432/cx_harness_dev",
            "development",
            DatabaseTargetClassification.LOCAL_DEVELOPMENT,
        ),
        (
            "postgresql://user:secret@db.example.internal/cx_harness",
            "production",
            DatabaseTargetClassification.PRODUCTION,
        ),
        (
            "postgresql://user:secret@service.oregon-postgres.render.com/db",
            "development",
            DatabaseTargetClassification.PRODUCTION,
        ),
        (
            "postgresql://user:secret@custom.remote.internal/cx_harness",
            "development",
            DatabaseTargetClassification.UNKNOWN,
        ),
        ("not-a-database-url", "development", DatabaseTargetClassification.UNKNOWN),
    ],
)
def test_database_target_classification(url, environment, expected) -> None:
    target = classify_database_target(url, environment)

    assert target.classification is expected
    assert not hasattr(target, "username")
    assert not hasattr(target, "password")


def test_sanitized_target_never_contains_credentials_or_full_url() -> None:
    target = classify_database_target(
        "postgresql://sensitive_user:super_secret@localhost:5432/safe_database",
        "development",
    )

    rendered = repr(target)
    assert "sensitive_user" not in rendered
    assert "super_secret" not in rendered
    assert target.host == "localhost"
    assert target.database == "safe_database"
