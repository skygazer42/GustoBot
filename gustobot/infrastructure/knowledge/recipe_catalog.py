"""Parse recipe and ingredient catalogs for the offline CSV export tools."""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IngredientAmount:
    """Normalized ingredient name, source amount text, and recipe role."""

    name: str
    amount: str | None
    role: str


@dataclass
class StepRecord:
    """One ordered recipe instruction after source normalization."""

    order: int
    instruction: str


@dataclass
class RecipeRecord:
    """Normalized recipe metadata, cooking steps, and ingredient groups."""

    name: str
    cook_time: str | None
    flavors: list[str]
    methods: list[str]
    dish_types: list[str]
    instructions: str | None
    steps: list[StepRecord]
    main_ingredients: list[IngredientAmount]
    aux_ingredients: list[IngredientAmount]
    cuisine_styles: list[str] = field(default_factory=list)


@dataclass
class IngredientProfile:
    """Optional nutrition and benefit text associated with one ingredient."""

    name: str
    nutrition: str | None
    benefits: list[str]


def load_recipe_records(recipe_json: Path) -> tuple[list[RecipeRecord], set[str]]:
    """Load structured recipe records from a JSON mapping."""
    payload = _load_json(recipe_json)
    return _normalise_recipes(payload)


def load_ingredient_profiles(
    ingredient_json: Path | None,
    ingredients_used: set[str],
) -> list[IngredientProfile]:
    """Return nutrition profiles for the subset of ingredients used in recipes."""
    if ingredient_json is None:
        return []

    payload = _load_json(ingredient_json)
    profiles: list[IngredientProfile] = []
    for name in sorted(ingredients_used):
        if name not in payload:
            continue
        raw = payload[name]
        if not isinstance(raw, dict):
            raise ValueError(  # noqa: TRY004 - invalid source record
                f"Ingredient profile must be an object: {name}"
            )
        nutrition = _clean_text(raw.get("营养价值"))
        benefits = _split_benefits(_clean_text(raw.get("食用功效")))
        profiles.append(IngredientProfile(name=name, nutrition=nutrition, benefits=benefits))
    return profiles


# --------------------------------------------------------------------------- #
# Internal helpers shared by import/export pipelines
# --------------------------------------------------------------------------- #
def _load_json(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON dataset not found: {path}")
    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        # Invalid JSON document shape is reported as a source value error.
        raise ValueError(f"Expected top-level object to be a dict in {path}")  # noqa: TRY004
    return payload


def _normalise_recipes(
    recipes_raw: dict[str, dict[str, object]],
) -> tuple[list[RecipeRecord], set[str]]:
    """Normalize recipe records and return the complete set of used ingredients."""
    records: list[RecipeRecord] = []
    ingredients_seen: set[str] = set()

    for raw_name, payload in recipes_raw.items():
        if not isinstance(payload, dict):
            raise ValueError(  # noqa: TRY004 - invalid source record
                f"Recipe record must be an object: {raw_name}"
            )

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
    text = _clean_text(value)
    if text is None:
        raise ValueError("Recipe and ingredient names must not be empty")
    return re.sub(r"\s+", " ", text)


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    if type(value) not in (str, int, float):
        raise ValueError("Recipe text fields must be strings or numbers")
    text = str(value).strip()
    return text or None


def _split_multi(value: object) -> list[str]:
    text = _clean_text(value)
    if text is None:
        return []
    parts = re.split(r"[、/,，；;]+", text)
    return [part.strip() for part in parts if part.strip()]


def _normalise_ingredients(
    value: object,
    *,
    role: str,
    seen: set[str],
) -> list[IngredientAmount]:
    """Normalize ingredient variants while preserving first-seen order and roles."""
    result: list[IngredientAmount] = []
    items: Iterable[object]
    if value is None:
        return result
    if isinstance(value, list):
        items = value
    else:
        raise ValueError(  # noqa: TRY004 - invalid source field
            "Recipe ingredient fields must be lists"
        )

    for item in items:
        if isinstance(item, (list, tuple)) and item:
            name = _clean_name(item[0])
            amount = _clean_text(item[1]) if len(item) > 1 else None
        elif isinstance(item, str):
            name = _clean_name(item)
            amount = None
        else:
            raise ValueError("Each ingredient must have a recorded name")
        seen.add(name)
        result.append(IngredientAmount(name=name, amount=amount, role=role))
    return result


def _normalise_steps(instructions: str | None) -> list[StepRecord]:
    """Split source instructions into ordered, nonempty recipe steps."""
    if not instructions:
        return []

    normalised = instructions.replace("：", ":")
    pattern = re.compile(r"(?P<order>\d+):\s*(?P<text>.*?)(?=(?:\d+:)|$)", re.DOTALL)
    matches = list(pattern.finditer(normalised))

    steps: list[StepRecord] = []
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


def _split_benefits(text: str | None) -> list[str]:
    if not text:
        return []
    lines = re.split(r"[\n\r]+", text)
    benefits: list[str] = []
    for line in lines:
        cleaned = line.strip()
        cleaned = re.sub(r"^[0-9]+[\\.、:：)\s]*", "", cleaned)
        if cleaned:
            benefits.append(cleaned)
    return benefits
