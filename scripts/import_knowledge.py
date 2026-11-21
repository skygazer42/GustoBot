"""Explicitly import recipe facts or source documents; no model extraction is implicit."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Iterator
from itertools import islice
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def create_service():
    """Create the ingestion service configured for the active domain."""
    from gustobot.interfaces.http.knowledge_router import get_ingestion_service

    return get_ingestion_service()


async def close_resources():
    """Close runtime clients and dispose the shared database engine."""
    from gustobot.application.services.knowledge_runtime import cleanup_runtime
    from gustobot.infrastructure.core.database import engine

    try:
        await cleanup_runtime()
    finally:
        await asyncio.to_thread(engine.dispose)


def _recipe_entries(payload: Any) -> Iterator[tuple[str, dict]]:
    """Yield recipe names and original records from either supported JSON shape."""
    if isinstance(payload, dict):
        for name, record in payload.items():
            if not isinstance(record, dict):
                raise TypeError("Each original recipe record must be an object")
            yield name, record
        return
    if not isinstance(payload, list):
        raise TypeError("Recipe JSON must be a name-to-record object or a list of records")
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise TypeError("Each recipe must provide a name and original record")
        record = item.get("record", item)
        if not isinstance(record, dict):
            raise TypeError("Each original recipe record must be an object")
        yield item["name"], record


async def import_path(
    command: str,
    path: Path,
    service,
    *,
    limit: int | None = None,
    source_id: str | None = None,
) -> int:
    """Import recipe records or one parsed document and return item count."""
    from gustobot.application.services.knowledge_ingestion import (
        DocumentIngestionRequest,
        parse_document,
    )

    path = path.resolve(strict=True)
    if command == "recipes":
        if limit is not None and limit < 1:
            raise ValueError("Recipe limit must be positive")
        payload = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8-sig"))
        count = 0
        entries = _recipe_entries(payload)
        if limit is not None:
            entries = islice(entries, limit)
        for name, record in entries:
            receipt = await service.ingest_recipe(name, record)
            print(receipt.model_dump_json(), flush=True)
            count += 1
        return count
    if command != "documents":
        raise ValueError("Import command must be recipes or documents")
    text = await asyncio.to_thread(parse_document, path)
    if source_id is None:
        identity = os.path.normcase(str(path))
        source_id = "file:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    request = DocumentIngestionRequest(text=text, source_id=source_id, uri=path.name)
    receipt = await service.ingest_document(request)
    print(receipt.model_dump_json(), flush=True)
    return 1


async def execute(args) -> int:
    """Run the selected import command and report failures without leaking secrets."""
    from gustobot.application.services.knowledge_ingestion import IngestionFailed

    try:
        service = create_service()
        count = await import_path(
            args.command,
            args.path,
            service,
            limit=args.limit if args.command == "recipes" else None,
            source_id=args.source_id if args.command == "documents" else None,
        )
        print(json.dumps({"completed": count, "kind": args.command}), flush=True)
        return 0
    except IngestionFailed as error:
        print(error.receipt.model_dump_json(), file=sys.stderr, flush=True)
        return 1
    except (OSError, ValueError, TypeError) as error:
        print(f"Import failed: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        await close_resources()


def _positive_limit(value: str) -> int:
    """Parse a strictly positive recipe import limit for argparse."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("limit must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    """Parse and execute an explicit recipe or document import command."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recipes = commands.add_parser(
        "recipes", help="Map original recipe JSON directly into graph facts"
    )
    recipes.add_argument("--path", type=Path, required=True)
    recipes.add_argument("--limit", type=_positive_limit)
    documents = commands.add_parser(
        "documents", help="Parse and index a document source explicitly"
    )
    documents.add_argument("--path", type=Path, required=True)
    documents.add_argument("--source-id")
    return asyncio.run(execute(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
