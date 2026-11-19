#!/usr/bin/env python3
"""
Batch import original recipe records into the fact graph via the HTTP API.

Example:
  python scripts/import_recipes.py --file data/recipe.json --batch-size 100
"""


import argparse
import json
import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _iter_payloads_from_json(
    raw: Any,
    *,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Yield KB recipe payloads from either:
    - dict keyed by recipe name (bundled data/recipe.json format)
    - list of recipe dicts (already-normalized)
    """

    emitted = 0

    if isinstance(raw, dict):
        for name, entry in raw.items():
            if limit is not None and emitted >= limit:
                return
            if not isinstance(entry, dict):
                raise TypeError(f"Recipe {name!r} must contain an object record")
            emitted += 1
            yield {"name": str(name), "record": entry}
        return

    if isinstance(raw, list):
        for item in raw:
            if limit is not None and emitted >= limit:
                return
            if not isinstance(item, dict):
                raise TypeError("Each recipe must be an object")
            name = next((item[field] for field in ("name", "title", "菜名") if field in item), None)
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Each recipe needs an explicit nonempty name")
            emitted += 1
            record = item.get("record", item)
            if not isinstance(record, dict):
                raise TypeError("Each recipe record must be an object")
            yield {"name": name, "record": record}
        return

    raise TypeError(f"Unsupported JSON root type: {type(raw)!r}")


def _chunked(iterable: Iterable[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    if size <= 0:
        raise ValueError("batch size must be positive")
    batch: list[dict[str, Any]] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _post_batch(
    client: httpx.Client,
    *,
    api_base_url: str,
    recipes: list[dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
    url = api_base_url.rstrip("/") + "/api/v1/knowledge/recipes/batch"
    response = client.post(url, json=recipes)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or len(payload) != len(recipes):
        raise ValueError("Import response must contain one receipt per recipe")
    if any(
        not isinstance(receipt, dict) or receipt.get("status") != "graph_ready"
        for receipt in payload
    ):
        raise ValueError("Each import receipt must report graph_ready")
    return len(payload), payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch import recipes into KB")
    parser.add_argument("--file", required=True, help="Path to recipe JSON file")
    parser.add_argument("--batch-size", type=int, default=100, help="Recipes per request")
    parser.add_argument(
        "--api-base-url",
        default="http://localhost:8000",
        help="Backend base URL (default: http://localhost:8000)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Only import first N recipes")
    parser.add_argument("--dry-run", action="store_true", help="Convert only, do not POST")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds")
    args = parser.parse_args(argv)
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit cannot be negative")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    json_path = Path(args.file)
    if not json_path.exists():
        print(f"File not found: {json_path}", file=sys.stderr)
        return 2

    with json_path.open("r", encoding="utf-8") as fp:
        raw = json.load(fp)

    payload_iter = _iter_payloads_from_json(raw, limit=args.limit)

    if args.dry_run:
        sample = []
        for idx, item in enumerate(payload_iter):
            if idx >= min(args.batch_size, 5):
                break
            sample.append(item)
        print(json.dumps(sample, ensure_ascii=False, indent=2))
        return 0

    total = 0
    started = time.time()

    with httpx.Client(timeout=args.timeout, trust_env=False) as client:
        for batch_idx, batch in enumerate(_chunked(payload_iter, args.batch_size), start=1):
            inserted, _payload = _post_batch(client, api_base_url=args.api_base_url, recipes=batch)
            total += inserted
            elapsed = time.time() - started
            rate = total / elapsed if elapsed > 0 else 0.0
            print(
                f"[batch {batch_idx}] sent={len(batch)} inserted={inserted} "
                f"total={total} rate={rate:.1f}/s"
            )

    print(f"Done. Imported {total} recipes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
