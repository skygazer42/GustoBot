"""
Deterministic helpers for importing recipe-like data into the KB API.

This module must stay pure (no Milvus/LLM calls) so it can be tested offline.
"""

import re
from typing import Any, Dict, List, Optional


_STEP_NUMBER_SPLIT_RE = re.compile(r"\s*\d+\s*[:：]\s*")


def _normalize_ingredient_pairs(value: Any) -> List[str]:
    """
    Normalize common ingredient shapes into a list of human-readable strings.

    Supported shapes:
    - [["香肠", "2根"], ["菜干", "200g"]]
    - {"香肠": "2根", "菜干": "200g"}
    - ["盐", "少许"]
    """

    if value is None:
        return []

    ingredients: List[str] = []

    if isinstance(value, dict):
        for name, amount in value.items():
            name_str = str(name).strip()
            amount_str = str(amount).strip() if amount is not None else ""
            if not name_str:
                continue
            ingredients.append(f"{name_str} {amount_str}".strip())
        return ingredients

    if isinstance(value, (list, tuple)):
        for item in value:
            if item is None:
                continue
            if isinstance(item, (list, tuple)):
                if not item:
                    continue
                name = str(item[0]).strip()
                amount = str(item[1]).strip() if len(item) > 1 and item[1] is not None else ""
                if name:
                    ingredients.append(f"{name} {amount}".strip())
                continue
            item_str = str(item).strip()
            if item_str:
                ingredients.append(item_str)
        return ingredients

    value_str = str(value).strip()
    return [value_str] if value_str else []


def split_steps(text: Optional[str]) -> List[str]:
    """Split a single '做法' string into a list of steps."""

    if not text:
        return []

    normalized = str(text).strip().replace("\r\n", "\n").replace("\r", "\n")
    if not normalized:
        return []

    if _STEP_NUMBER_SPLIT_RE.search(normalized):
        parts = [part.strip() for part in _STEP_NUMBER_SPLIT_RE.split(normalized) if part.strip()]
        return parts

    if "\n" in normalized:
        return [line.strip() for line in normalized.split("\n") if line.strip()]

    # Fallback: split by common sentence separators.
    parts = [part.strip() for part in re.split(r"[。；;]\s*", normalized) if part.strip()]
    return parts


def recipe_json_entry_to_recipe(name: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map one entry from data/recipe.json into the KB API recipe payload.

    The bundled dataset uses Chinese keys like 主食材/辅料/做法/类型.
    """

    main_ingredients = _normalize_ingredient_pairs(entry.get("主食材"))
    extra_ingredients = _normalize_ingredient_pairs(entry.get("辅料"))
    ingredients = [*main_ingredients, *extra_ingredients]

    steps = split_steps(entry.get("做法"))

    tips_parts: List[str] = []
    taste = entry.get("口味")
    if taste:
        tips_parts.append(f"口味：{taste}")
    craft = entry.get("工艺")
    if craft:
        tips_parts.append(f"工艺：{craft}")
    tips = "；".join(tips_parts) if tips_parts else None

    payload: Dict[str, Any] = {
        "name": name,
        "category": entry.get("类型"),
        "time": entry.get("耗时"),
        "ingredients": ingredients or None,
        "steps": steps or None,
        "tips": tips,
    }
    return payload
