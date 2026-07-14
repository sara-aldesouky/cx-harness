"""Small shared validation helpers for read-only repositories."""

from collections.abc import Collection


DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class RepositoryValidationError(ValueError):
    """Raised when repository query parameters are invalid."""


def validate_pagination(limit: int, offset: int) -> None:
    """Validate consistent repository pagination bounds."""

    if not isinstance(limit, int) or isinstance(limit, bool):
        raise RepositoryValidationError("limit must be an integer")
    if not 1 <= limit <= MAX_LIMIT:
        raise RepositoryValidationError(
            f"limit must be between 1 and {MAX_LIMIT}"
        )
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise RepositoryValidationError("offset must be an integer")
    if offset < 0:
        raise RepositoryValidationError("offset must be non-negative")


def validate_filter(value: str, allowed: Collection[str], field_name: str) -> None:
    """Reject unsupported constrained-string filter values."""

    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise RepositoryValidationError(
            f"unsupported {field_name} {value!r}; expected one of: {choices}"
        )
