"""Verify connectivity to the configured PostgreSQL database."""

import sys

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database.session import DatabaseConfigurationError, get_engine


def main() -> int:
    """Run a read-only connectivity query and report the result."""

    try:
        with get_engine().connect() as connection:
            result = connection.execute(text("SELECT 1")).scalar_one()
    except DatabaseConfigurationError as error:
        print(f"Database connection failed: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError as error:
        print(
            f"Database connection failed ({type(error).__name__}): {error}",
            file=sys.stderr,
        )
        return 1

    if result != 1:
        print(f"Database connection failed: SELECT 1 returned {result!r}.", file=sys.stderr)
        return 1

    print("Database connection successful: SELECT 1 returned 1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
