"""
Shared data parsing utilities for recipe knowledge graph bootstrapping.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass
class IngredientAmount:
    name: str
    amount: Optional[str]
    role: str


@dataclass
class StepRecord:
    order: int
    instruction: str


@dataclass
class RecipeRecord:
    name: str
    cook_time: Optional[str]
    flavors: List[str]
    methods: List[str]
    dish_types: List[str]
    instructions: Optional[str]
    steps: List[StepRecord]
    main_ingredients: List[IngredientAmount]
    aux_ingredients: List[IngredientAmount]
    cuisine_styles: List[str] = field(default_factory=list)


@dataclass
class IngredientProfile:
    name: str
    nutrition: Optional[str]
    benefits: List[str]


def load_recipe_records(recipe_json: Path) -> Tuple[List[RecipeRecord], Set[str]]:
    """Load structured recipe records from a JSON mapping."""
    payload = _load_json(recipe_json)
    return _normalise_recipes(payload)


def load_ingredient_profiles(
    ingredient_json: Optional[Path],
    ingredients_used: Set[str],
) -> List[IngredientProfile]:
    """Return nutrition profiles for the subset of ingredients used in recipes."""
    if not ingredient_json or not ingredient_json.is_file():
        return []

    payload = _load_json(ingredient_json)
    profiles: List[IngredientProfile] = []
    for name in sorted(ingredients_used):
        raw = payload.get(name)
        if not isinstance(raw, dict):
            continue
        nutrition = _clean_text(raw.get("营养价值"))
        benefits = _split_benefits(_clean_text(raw.get("食用功效")))
        profiles.append(IngredientProfile(name=name, nutrition=nutrition, benefits=benefits))
    return profiles


# --------------------------------------------------------------------------- #
# Internal helpers shared by import/export pipelines
# --------------------------------------------------------------------------- #
def _load_json(path: Path) -> Dict[str, Dict[str, object]]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON dataset not found: {path}")
    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected top-level object to be a dict in {path}")
    return payload


def _normalise_recipes(
    recipes_raw: Dict[str, Dict[str, object]],
) -> Tuple[List[RecipeRecord], Set[str]]:
    records: List[RecipeRecord] = []
    ingredients_seen: Set[str] = set()

    for raw_name, payload in recipes_raw.items():
        if not isinstance(payload, dict):
            continue

        name = _clean_name(raw_name)
        cook_time = _clean_text(payload.get("耗时"))
        flavors = _split_multi(payload.get("口味"))
        methods = _split_multi(payload.get("工艺"))
        dish_types = _split_multi(payload.get("类型"))
        instructions = _clean_text(payload.get("做法"))

        main_ingredients = _normalise_ingredients(
            payload.get("主食材", payload.get("主料")),
            role="main",
            seen=ingredients_seen,
        )
        aux_ingredients = _normalise_ingredients(
            payload.get("辅料"), role="aux", seen=ingredients_seen
        )
        steps = _normalise_steps(instructions)

        records.append(
            RecipeRecord(
                name=name,
                cook_time=cook_time,
                flavors=flavors,
                methods=methods,
                dish_types=dish_types,
                instructions=instructions,
                steps=steps,
                main_ingredients=main_ingredients,
                aux_ingredients=aux_ingredients,
                cuisine_styles=_split_multi(payload.get("菜系")),
            ),
        )

    return records, ingredients_seen


def _clean_name(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _clean_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _split_multi(value: object) -> List[str]:
    if not value:
        return []
    text = str(value)
    parts = re.split(r"[、/,，；;]+", text)
    return [part.strip() for part in parts if part.strip()]


def _normalise_ingredients(
    value: object,
    *,
    role: str,
    seen: Set[str],
) -> List[IngredientAmount]:
    result: List[IngredientAmount] = []
    items: Iterable[object]
    if isinstance(value, list):
        items = value
    else:
        items = []

    for item in items:
        if isinstance(item, (list, tuple)) and item:
            name = _clean_name(item[0])
            amount = _clean_text(item[1]) if len(item) > 1 else None
        elif isinstance(item, str):
            name = _clean_name(item)
            amount = None
        else:
            continue
        if not name:
            continue
        seen.add(name)
        result.append(IngredientAmount(name=name, amount=amount, role=role))
    return result


def _normalise_steps(instructions: Optional[str]) -> List[StepRecord]:
    if not instructions:
        return []

    normalised = instructions.replace("：", ":")
    pattern = re.compile(r"(?P<order>\d+):\s*(?P<text>.*?)(?=(?:\d+:)|$)", re.S)
    matches = list(pattern.finditer(normalised))

    steps: List[StepRecord] = []
    if matches:
        for match in matches:
            order = int(match.group("order"))
            text = match.group("text").strip().rstrip("。.")
            if text:
                steps.append(StepRecord(order=order, instruction=text))
    else:
        fragments = re.split(r"[。.!？！\n]+", normalised)
        filtered = [fragment.strip() for fragment in fragments if fragment.strip()]
        for index, fragment in enumerate(filtered, start=1):
            steps.append(StepRecord(order=index, instruction=fragment))
    return steps


def _split_benefits(text: Optional[str]) -> List[str]:
    if not text:
        return []
    lines = re.split(r"[\n\r]+", text)
    benefits: List[str] = []
    for line in lines:
        cleaned = line.strip()
        cleaned = re.sub(r"^[0-9]+[\\.、:：)\s]*", "", cleaned)
        if cleaned:
            benefits.append(cleaned)
    return benefits
