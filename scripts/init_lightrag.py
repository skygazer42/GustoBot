#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LightRAG 初始化脚本

从菜谱 JSON 文件导入同一 LightRAG 文档与关系索引。
其他领域使用通用文档或事实导入 API。
"""
import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Iterable, Tuple
import json
import logging

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

if TYPE_CHECKING:
    from gustobot.application.services.lightrag_service import LightRAGService

logger = logging.getLogger("init-lightrag")


def format_recipe_document(record: Dict[str, Any]) -> str:
    """
    将菜谱 JSON 记录格式化为 LightRAG 文档格式

    Parameters
    ----------
    record : Dict[str, Any]
        标准化后的菜谱记录

    Returns
    -------
    str
        格式化后的菜谱文档
    """
    dish_name = record["dish_name"]
    instructions = record.get("instructions", "")
    cook_time = record.get("cook_time", "")
    ingredients = record.get("ingredients", [])
    flavors = record.get("flavors", [])
    methods = record.get("methods", [])
    dish_types = record.get("types", [])

    # 格式化文档
    doc_parts = [f"# {dish_name}\n"]

    if flavors:
        doc_parts.append(f"**口味**: {', '.join(flavors)}")

    if methods:
        doc_parts.append(f"**烹饪方法**: {', '.join(methods)}")

    if dish_types:
        doc_parts.append(f"**菜品类型**: {', '.join(dish_types)}")

    if cook_time:
        doc_parts.append(f"**烹饪时长**: {cook_time}")

    if ingredients:
        doc_parts.append("\n**食材**:\n")
        for ing in ingredients:
            if isinstance(ing, dict):
                name = ing["name"]
                if name is None:
                    continue
                amount = ing.get("amount")
                doc_parts.append(
                    f"- {name}: {amount}" if amount is not None and amount != "" else f"- {name}"
                )
            else:
                doc_parts.append(f"- {ing}")

    if instructions:
        doc_parts.append(f"\n**做法**:\n{instructions}")

    return "\n".join(doc_parts)


async def import_from_json(
    lightrag: "LightRAGService", json_path: str, limit: Optional[int] = None
) -> int:
    """
    从 JSON 文件导入菜谱数据到 LightRAG

    Parameters
    ----------
    lightrag : LightRAGService
        LightRAG API 实例
    json_path : str
        JSON 文件路径
    limit : int, optional
        限制导入的菜品数量，用于测试

    Returns
    -------
    int
        导入的文档数量
    """
    if limit is not None and limit < 0:
        raise ValueError("limit cannot be negative")
    if limit == 0:
        return 0
    logger.info(f"开始从 JSON 文件导入: {json_path}")

    raw_recipes = json.loads(await asyncio.to_thread(Path(json_path).read_text, encoding="utf-8"))

    recipes = _normalize_recipe_payload(raw_recipes)

    if limit is not None:
        recipes = recipes[:limit]

    documents = []

    for recipe in recipes:
        doc = format_recipe_document(recipe)
        documents.append(doc)

        if len(documents) % 10 == 0:
            logger.info(f"已准备 {len(documents)} 个文档")

    logger.info(f"共准备了 {len(documents)} 个菜谱文档")

    # 批量插入到 LightRAG
    logger.info("开始插入文档到 LightRAG")
    result = await lightrag.insert_documents(documents)

    logger.info("导入完成: 总数=%s, 成功=%s, 失败=%s", result.total, result.success, result.failed)

    return result.success


def _normalize_recipe_payload(raw: Any) -> List[Dict[str, Any]]:
    """
    将 JSON 原始数据统一转换为列表格式，确保包含 dish_name 等关键字段。
    支持以下输入格式：
      1. 列表: [ {...}, {...} ]
      2. 字典: { "菜名": {...}, ... }
    """
    entries: Iterable[Tuple[Optional[str], Any]]
    if isinstance(raw, dict):
        entries = raw.items()
    elif isinstance(raw, list):
        entries = ((None, entry) for entry in raw)
    else:
        raise ValueError("不支持的菜谱数据格式，期望为 list 或 dict。")

    from gustobot.infrastructure.knowledge.recipe_import import recipe_json_entry_to_recipe

    records = []
    for source_name, payload in entries:
        if not isinstance(payload, dict):
            raise TypeError("每个菜谱条目必须为对象")
        record = dict(payload)
        dish_name = (
            record.get("dish_name")
            or source_name
            or record.get("dishName")
            or record.get("name")
            or record.get("title")
        )
        if not isinstance(dish_name, str) or not dish_name.strip():
            raise ValueError("菜谱必须提供非空菜名")
        record["dish_name"] = dish_name
        if any(key in record for key in ("主食材", "辅料", "做法")):
            recipe = recipe_json_entry_to_recipe(dish_name, record)
            record.update(
                cook_time=recipe["time"],
                ingredients=recipe["ingredients"],
                instructions="\n".join(recipe["steps"]) if recipe["steps"] is not None else "",
            )
        records.append(record)
    return records


async def main():
    """主函数"""
    from gustobot.application.services.lightrag_service import LightRAGService
    from gustobot.config import settings
    from gustobot.config.domain import get_domain_definition

    from gustobot.infrastructure.core.resources import close_on_exit

    import argparse

    parser = argparse.ArgumentParser(description="LightRAG 初始化脚本")
    parser.add_argument(
        "--source",
        type=str,
        choices=["json"],
        default="json",
        help="菜谱 JSON 数据源",
    )
    parser.add_argument(
        "--json-path",
        type=str,
        default=str(project_root / "data" / "recipe.json"),
        help="JSON 文件路径（当 source=json 时使用）",
    )
    parser.add_argument("--limit", type=int, default=None, help="限制导入数量（用于测试）")
    parser.add_argument(
        "--working-dir", type=str, default=None, help="LightRAG 工作目录（覆盖配置文件）"
    )

    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        parser.error("--limit cannot be negative")
    domain = get_domain_definition()
    if domain.id != "recipes":
        parser.error(
            "This is a recipe-only importer; select the recipes domain configuration "
            "before importing recipe JSON data."
        )

    try:
        # 创建 LightRAG API 实例
        logger.info("初始化 LightRAG")
        lightrag = LightRAGService(
            working_dir=args.working_dir,
            default_mode=settings.LIGHTRAG_RETRIEVAL_MODE,
            default_top_k=settings.LIGHTRAG_TOP_K,
        )

        async with close_on_exit(lightrag.cleanup):
            count = await import_from_json(lightrag, args.json_path, limit=args.limit)

            logger.info("LightRAG 初始化完成，成功导入 %s 个菜谱文档", count)
            logger.info("工作目录: %s", lightrag.working_dir)
            logger.info("检索模式: %s", lightrag.default_mode)

    except Exception:
        logger.exception("LightRAG 初始化失败")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
