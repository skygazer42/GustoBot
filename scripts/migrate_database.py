"""Explicitly initialize or advance the application MySQL schema."""

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Read schema readiness without applying migrations"
    )
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from gustobot.infrastructure.core.database import engine, migrate_database
    except ValueError as exc:
        parser.error(str(exc))

    try:
        if args.check:
            from migrations import check_database_schema

            check_database_schema(engine)
            revisions = []
        else:
            revisions = migrate_database(engine)
    finally:
        engine.dispose()
    if revisions:
        print("Applied schema revisions: " + ", ".join(revisions))
    else:
        print("Application schema is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
