"""Filesystem-safe deterministic download names."""

import re
from datetime import datetime, timezone


def safe_component(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.").lower()
    return value[:80] or "report"


def run_filename(model_name: str, created_at: datetime, extension: str) -> str:
    day = created_at.astimezone(timezone.utc).date().isoformat()
    return f"benchmark-run-{safe_component(model_name)}-{day}.{extension}"


def comparison_filename(suite_key: str, suite_version: str, generated_at: datetime, extension: str) -> str:
    day = generated_at.astimezone(timezone.utc).date().isoformat()
    return f"benchmark-comparison-{safe_component(suite_key)}-{safe_component(suite_version)}-{day}.{extension}"
