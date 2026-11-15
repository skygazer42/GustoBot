#!/usr/bin/env python3
"""Queue pgvector Excel ingestion and add sample recipes to the backend KB."""

import asyncio
from pathlib import Path

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXCEL_FILE = PROJECT_ROOT / "data" / "kb" / "历史菜谱源头.xlsx"
INGEST_URL = "http://localhost:8100"
BACKEND_URL = "http://localhost:8000"
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=120, connect=10)


async def init_pgvector_from_excel():
    """Upload the local workbook so the service need not share its filesystem."""
    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
        with EXCEL_FILE.open("rb") as workbook:
            form = aiohttp.FormData()
            form.add_field(
                "file",
                workbook,
                filename=EXCEL_FILE.name,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            form.add_field("incremental", "false")
            async with session.post(
                f"{INGEST_URL}/api/v1/knowledge/ingest/excel/upload", data=form
            ) as response:
                response.raise_for_status()
                result = await response.json()
    print(f"Excel processing queued: {result}")
    return True


async def add_sample_recipes():
    """Add sample recipes through the backend's recipe API."""
    recipes = [
        {
            "name": "麻婆豆腐",
            "description": "四川传统名菜，麻、辣、鲜、香、烫、整、嫩、酥。由豆腐、牛肉末、豆瓣酱和花椒等制成。",
            "category": "川菜",
            "history": "麻婆豆腐始创于清朝同治年间，由成都万福桥陈兴盛饭铺老板娘刘陈氏所创。因她脸上有麻点，人称陈麻婆。",
            "ingredients": ["豆腐", "牛肉末", "豆瓣酱", "花椒", "葱", "姜", "蒜"],
            "steps": ["豆腐切块焯水", "炒制牛肉末", "加入豆瓣酱炒出红油", "加入豆腐和调料"],
        },
        {
            "name": "宫保鸡丁",
            "description": "川菜传统名菜，鸡丁配花生米，红而不辣，辣而不猛，香辣味浓，肉质滑脆。",
            "category": "川菜",
            "history": "宫保鸡丁源于清朝，由山东巡抚丁宝桢发明。丁宝桢曾任宫保官职，故此菜被称为宫保鸡丁。",
            "ingredients": ["鸡胸肉", "花生米", "干辣椒", "花椒", "葱", "姜", "蒜"],
            "steps": ["鸡胸肉切丁腌制", "调制宫保汁", "炒制鸡丁", "加入花生和调料"],
        },
        {
            "name": "东坡肉",
            "description": "江南名菜，五花肉慢炖而成，色泽红亮，酥烂而形不碎，香糯而不腻口。",
            "category": "浙菜",
            "history": (
                "东坡肉相传为北宋文学家苏东坡所创。苏东坡在杭州任职时，曾组织民工疏浚西湖，"
                "百姓感念其德，送来猪肉。苏东坡让家人将猪肉切成方块，烹制成红烧肉回赠给民工。"
            ),
            "ingredients": ["五花肉", "冰糖", "酱油", "料酒", "葱", "姜"],
            "steps": ["五花肉切块焯水", "炒糖色", "加入肉块翻炒", "慢炖收汁"],
        },
    ]

    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
        async with session.post(
            f"{BACKEND_URL}/api/v1/knowledge/recipes/batch", json=recipes
        ) as response:
            response.raise_for_status()
            statistics = (await response.json())["statistics"]
    if statistics["error"] or statistics["success"] != len(recipes):
        raise RuntimeError(f"Sample recipe import incomplete: {statistics}")
    print(f"Imported {statistics['success']} sample recipes")
    return True


async def wait_and_check():
    """Read backend statistics; they do not certify background Excel completion."""
    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
        async with session.get(f"{BACKEND_URL}/api/v1/knowledge/stats") as response:
            response.raise_for_status()
            data = (await response.json())["data"]
    print(f"Backend knowledge base statistics: {data}")
    return data["document_count"]


async def test_search():
    """Probe sample retrieval and propagate request failures."""
    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
        for query in ["麻婆豆腐历史", "宫保鸡丁来历", "东坡肉典故", "川菜特色"]:
            async with session.post(
                f"{BACKEND_URL}/api/v1/knowledge/search", json={"query": query, "top_k": 3}
            ) as response:
                response.raise_for_status()
                results = (await response.json())["results"]
            print(f"{query}: {len(results)} results")


async def main():
    await init_pgvector_from_excel()
    await add_sample_recipes()
    await wait_and_check()
    await test_search()
    print("Sample recipes imported; Excel processing was queued on the ingestion service.")


if __name__ == "__main__":
    asyncio.run(main())
