"""Explicitly inspect or rebuild numeric projections in the current model scope."""

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parser() -> argparse.ArgumentParser:
    """Define the read-only audit and explicit numeric projection publish modes."""
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Audit and report without writing (default)",
    )
    mode.add_argument(
        "--publish",
        action="store_true",
        help="Update current scoped derived values and advance its revision",
    )
    result.add_argument("--batch-size", type=int, default=100)
    return result


async def rebuild(arguments: argparse.Namespace) -> None:
    """Audit or rebuild scoped numeric projections and always close runtime clients."""
    from gustobot.application.services.knowledge_runtime import (
        cleanup_runtime,
        get_graph_store,
    )

    try:
        store = get_graph_store()
        report = await store.rebuild_numeric_projection(
            dry_run=not arguments.publish, batch_size=arguments.batch_size
        )
        print(report.model_dump_json(indent=2))
    finally:
        await cleanup_runtime()


if __name__ == "__main__":
    asyncio.run(rebuild(parser().parse_args()))
