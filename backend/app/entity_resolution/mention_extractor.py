"""Deterministic public order-number extraction from customer-authored text."""

from __future__ import annotations

import re

from app.conversation_state import EntityType
from app.entity_resolution.contracts import EntityMention


_ORDER_REFERENCE_PATTERN = re.compile(
    r"(?i)(?<![A-Z0-9])(?:ORD-\d{5}|CX-[A-Z0-9]+(?:-[A-Z0-9]+)+)(?![A-Z0-9])"
)
_ORDER_LIKE_PATTERN = re.compile(
    r"(?i)(?<![A-Z0-9])(?:ORD|CX)-[^\s,.;!?]+"
)
_CORRECTION_PATTERN = re.compile(
    r"(?i)(?:\b(?:no|rather|instead|i\s+mean)\b|(?:لا|لأ)\s*[،,]?\s*(?:قصدي|اقصد|أقصد))"
)


class OrderMentionExtractor:
    """Recognize complete public order references without guessing."""

    def extract(self, customer_message: str) -> tuple[EntityMention, ...]:
        if not isinstance(customer_message, str):
            raise TypeError("customer_message must be a string")
        mentions = []
        for match in _ORDER_REFERENCE_PATTERN.finditer(customer_message):
            prefix = customer_message[max(0, match.start() - 32) : match.start()]
            mentions.append(
                EntityMention(
                    entity_type=EntityType.ORDER,
                    public_reference=match.group(0),
                    span_start=match.start(),
                    span_end=match.end(),
                    is_correction=bool(_CORRECTION_PATTERN.search(prefix)),
                )
            )
        return tuple(mentions)

    def contains_malformed_reference(self, customer_message: str) -> bool:
        """Detect explicit order-like tokens that are not accepted references."""

        valid_spans = {
            (match.start(), match.end())
            for match in _ORDER_REFERENCE_PATTERN.finditer(customer_message)
        }
        return any(
            (match.start(), match.end()) not in valid_spans
            for match in _ORDER_LIKE_PATTERN.finditer(customer_message)
        )
