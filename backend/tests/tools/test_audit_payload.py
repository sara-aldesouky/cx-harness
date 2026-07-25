"""Unit tests for centralized audit payload safety."""

import json

from app.tools.audit_payload import REDACTED_MARKER, sanitize_audit_payload


def test_redacts_sensitive_keys_recursively_without_mutating_input() -> None:
    original = {
        "password": "top-secret",
        "nested": {
            "Email": "person@example.test",
            "items": [{"API_KEY": "key", "order_id": "safe-order"}],
        },
        "customer_id": "safe-customer",
        "conversation_id": "safe-conversation",
        "execution_id": "safe-execution",
    }

    result = sanitize_audit_payload(original, 10_000)

    assert result.payload["password"] == REDACTED_MARKER
    assert result.payload["nested"]["Email"] == REDACTED_MARKER
    assert result.payload["nested"]["items"][0]["API_KEY"] == REDACTED_MARKER
    assert result.payload["nested"]["items"][0]["order_id"] == REDACTED_MARKER
    assert result.payload["customer_id"] == REDACTED_MARKER
    assert result.payload["conversation_id"] == REDACTED_MARKER
    assert result.payload["execution_id"] == REDACTED_MARKER
    assert original["password"] == "top-secret"
    assert original["nested"]["Email"] == "person@example.test"


def test_payload_below_and_exactly_at_limit_is_preserved() -> None:
    payload = {"message": "safe"}
    expected_size = len(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )

    below = sanitize_audit_payload(payload, expected_size + 1)
    exact = sanitize_audit_payload(payload, expected_size)

    assert below.payload == payload and below.truncated is False
    assert exact.payload == payload and exact.truncated is False


def test_oversized_payload_becomes_valid_json_truncation_metadata() -> None:
    secret = "never-store-this-oversized-value-" * 20
    result = sanitize_audit_payload({"content": secret}, 20)

    assert result.truncated is True
    assert result.payload == {
        "_truncated": True,
        "_original_size_bytes": result.original_size_bytes,
    }
    assert result.original_size_bytes > 20
    assert secret not in json.dumps(result.payload)
    assert json.loads(json.dumps(result.payload)) == result.payload
