#!/usr/bin/env python3
"""Queue Excel ingestion and load text/recipes through the supported KB interfaces."""

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


INGEST_URL = "http://localhost:8000"
TEXT_FILE = PROJECT_ROOT / "data" / "kb" / "data.txt"
RECIPE_FILE = PROJECT_ROOT / "data" / "recipe.json"
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=120, connect=10)


async def load_excel_to_pgvector():
    """Submit an Excel workbook; HTTP 202 acknowledges queueing, not completion."""
    from scripts.init_pgvector_simple import init_pgvector_from_excel

    return await init_pgvector_from_excel()


async def load_text_to_milvus():
    """Use the existing document service; there is no HTTP documents/batch route."""
    from gustobot.infrastructure.knowledge import KnowledgeService
    from gustobot.infrastructure.core.resources import close_on_exit

    content = await asyncio.to_thread(TEXT_FILE.read_text, encoding="utf-8")
    service = await asyncio.to_thread(KnowledgeService)
    async with close_on_exit(service.close):
        result = await service.ingest_text(
            content, metadata={"source": TEXT_FILE.name, "type": "milvus_data"}
        )
        print(f"Imported {result['add_count']} text chunks into Milvus")
        return result


async def load_json_recipes():
    """Normalize the bundled name-keyed dataset with the shared recipe importer."""
    from scripts.import_recipes import _iter_payloads_from_json

    raw = json.loads(await asyncio.to_thread(RECIPE_FILE.read_text, encoding="utf-8"))
    recipes = list(_iter_payloads_from_json(raw, limit=50))
    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
        async with session.post(
            f"{INGEST_URL}/api/v1/knowledge/recipes/batch", json=recipes
        ) as response:
            response.raise_for_status()
            result = await response.json()
    statistics = result["statistics"]
    if statistics["error"] or statistics["success"] != len(recipes):
        raise RuntimeError(f"Recipe import incomplete: {statistics}")
    print(f"Imported {statistics['success']} recipes")
    return statistics


async def check_kb_stats():
    """Return actual backend statistics and propagate HTTP/schema failures."""
    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
        async with session.get(f"{INGEST_URL}/api/v1/knowledge/stats") as response:
            response.raise_for_status()
            data = (await response.json())["data"]
    print(f"Knowledge base statistics: {data}")
    return data


async def test_search():
    """Probe vector retrieval without hiding HTTP errors as empty results."""
    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
        for query in ["麻婆豆腐", "川菜历史", "宫保鸡丁做法", "菜谱文化"]:
            async with session.post(
                f"{INGEST_URL}/api/v1/knowledge/search", json={"query": query, "top_k": 3}
            ) as response:
                response.raise_for_status()
                results = (await response.json())["results"]
            print(f"{query}: {len(results)} results")


async def main():
    await load_excel_to_pgvector()
    await load_text_to_milvus()
    await load_json_recipes()
    await check_kb_stats()
    await test_search()
    print("Milvus loading finished; Excel processing was queued on the ingestion service.")


if __name__ == "__main__":
    asyncio.run(main())
