"""用官方食物成分和明确用量补全营养；区分投料小计与实际成菜摄入。"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NUTRIENTS = (
    "energy_kcal",
    "protein_g",
    "fat_g",
    "carbohydrate_g",
    "fiber_g",
    "calcium_mg",
    "iron_mg",
    "potassium_mg",
    "sodium_mg",
    "vitamin_c_mg",
    "vitamin_a_rae_ug",
)
_NUMBER = r"\d+(?:\.\d+)?"
_RANGE = rf"({_NUMBER})(?:\s*[-–—~～至]\s*({_NUMBER}))?"
_MEASURES = re.compile(rf"(?<![\d.]){_RANGE}\s*(kg|千克|g|克|ml|毫升|l|升|斤)", re.I)
_COUNTS = re.compile(rf"{_RANGE}\s*(个|只|枚|瓣|根|颗|头)")


class NutritionModel(BaseModel):
    """营养计算配置和产物拒绝未知字段及隐式字符串数值。"""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class RegisteredNutritionBatch(NutritionModel):
    """将修订批次绑定到独立版本的成分表及用量匹配。"""

    id: str
    profiles: str
    matches: str


class NutritionRegistry(NutritionModel):
    """新批次的补充资料不得静默改变已发布批次的营养结果。"""

    schema_version: Literal[1]
    batches: list[RegisteredNutritionBatch]


class FoodAlias(NutritionModel):
    """精确食材名称与官方食物状态的人工核对结果。"""

    names: list[str] = Field(min_length=1)
    food_key: str
    match_note: str
    count_portion_modifier: str | None = None
    volume_portion_modifier: str | None = None
    volume_portion_ml: float | None = Field(default=None, gt=0)
    exclude_recipe_mass: bool = False


class IngredientOverride(NutritionModel):
    """逐菜解决通用名称无法表达的干湿、部位、品牌和投料条件。"""

    row: int = Field(ge=1)
    ingredient_name: str
    food_key: str | None
    reason: str
    grams_min: float | None = Field(default=None, ge=0)
    grams_max: float | None = Field(default=None, ge=0)
    calculation_note: str | None = None


class ExcludedIngredient(NutritionModel):
    """名称虽存在，但当前资料不足以对应具体营养档案。"""

    names: list[str]
    reason: str


class IngredientMatches(NutritionModel):
    """可审阅的精确匹配表；不以相似字符串猜食材或食品状态。"""

    schema_version: Literal[1]
    aliases: list[FoodAlias]
    row_overrides: list[IngredientOverride]
    exclusion_names: list[ExcludedIngredient]
    recipe_reference_foods: list[RecipeReferenceFoods] = Field(default_factory=list)


class RecipeReferenceFoods(NutritionModel):
    """复合食品无确切品牌时，另列官方示例，不混入当前配方计算。"""

    row: int = Field(ge=1)
    food_keys: list[str]
    reason: str


class NutrientRange(NutritionModel):
    """范围表达投料不确定性；未知营养值保持为空。"""

    minimum: float | None
    maximum: float | None


class NutrientSubtotal(NutrientRange):
    """记录哪些已称量原料缺该营养值，防止把部分和冒充完整值。"""

    included_ingredients: list[str]
    missing_values_for: list[str]


class IngredientNutrition(NutritionModel):
    """一项食材的官方事实、用量换算与计入边界。"""

    name: str
    amount_text: str | None
    status: Literal["calculated", "reference_only", "unmatched"]
    food_key: str | None = None
    official_description: str | None = None
    source_url: str | None = None
    source_food_id: str | None = None
    state: str | None = None
    match_note: str
    per_100g: dict[str, float | None] = Field(default_factory=dict)
    grams_min: float | None = None
    grams_max: float | None = None
    quantity_note: str
    contribution: dict[str, NutrientRange] = Field(default_factory=dict)


class NutritionNote(NutritionModel):
    """官方一般营养素作用及适用边界，不是菜肴功效承诺。"""

    statement: str
    source_url: str
    scope: str


class RecipeNutrition(NutritionModel):
    """可复算的原料营养补充，不假称成菜检测或实际摄入量。"""

    method: Literal["official_food_composition_input_calculation"]
    scope: Literal["listed_input_total", "known_input_subtotal", "ingredient_reference_only"]
    basis: str
    profiles_sha256: str
    matches_sha256: str
    ingredients: list[IngredientNutrition]
    not_in_subtotal: list[str] = Field(default_factory=list)
    reference_foods: list[IngredientNutrition] = Field(default_factory=list)
    subtotal: dict[str, NutrientSubtotal]
    nutrient_notes: list[NutritionNote]
    interpretation: list[str]


def _name(value: str) -> str:
    """只统一字符宽度与空白，不删除改变食品含义的限定词。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def _portion(food: dict, modifier: str) -> dict:
    """份量名称须唯一且完整匹配，不能随意取相似量具。"""
    portions: list[dict] = [
        portion for portion in food["portions"] if portion["modifier"] == modifier
    ]
    if len(portions) != 1 or portions[0]["amount"] <= 0:
        raise ValueError(f"Official portion must match uniquely: {food['key']} / {modifier}")
    return portions[0]


def _quantity(
    amount: str | None, alias: FoodAlias | None, food: dict, override: IngredientOverride | None
) -> tuple[float | None, float | None, str]:
    """仅换算明确数字和有官方份量的量具；不执行份数表达式。"""
    if override is not None:
        if override.grams_min is None:
            return None, None, override.reason
        maximum = override.grams_min if override.grams_max is None else override.grams_max
        if maximum < override.grams_min:
            raise ValueError("Ingredient gram range is reversed")
        note = override.reason
        if override.calculation_note is not None:
            note += f"；{override.calculation_note}"
        return override.grams_min, maximum, note
    if alias is None or alias.exclude_recipe_mass:
        return None, None, "原料规格、可食部或留存量没有明确依据，不将采购/投料重量代入"
    if amount is None:
        return None, None, "未记录可换算的实际用量；保留官方每100g原料资料"
    text = unicodedata.normalize("NFKC", amount)
    if re.search(r"油炸|炸制|炸丸|油浴|炸物|份数|\bMo\b|[*×]", text):
        return None, None, "含油浴投料或未实例化份数公式，不能据此计算实际用量"
    if re.search(r"[≥≤<>]|至少|至多|不少于|不超过|以上|以下", text):
        return None, None, "仅有用量下限或上限，没有闭合范围或实际称量值"
    if "或" in text or "每" in text:
        return None, None, "有替代用量或每件/总量歧义，需按本次实际称量计算"
    measures = list(_MEASURES.finditer(text))
    if measures:
        if re.search(r"总量|合计|共约|共", text[: measures[0].start()]):
            measures = measures[:1]
        if len(measures) > 1:
            first = measures[0]
            rest = measures[1:]
            is_total = (
                all(match.group(3).lower() == first.group(3).lower() for match in rest)
                and float(first.group(1)) == sum(float(match.group(1)) for match in rest)
                and first.group(2) is None
                and all(match.group(2) is None for match in rest)
                and re.search(r"[（(:：]|其中|分配", text[first.end() : rest[0].start()])
            )
            if is_total:
                measures = [first]
            elif not re.search(r"[;；+]", text):
                return None, None, "同一原料含多个重量，未明确为分阶段加量或总量分配"
        units = {match.group(3).lower() for match in measures}
        if len(units) != 1:
            return None, None, "同一原料含不同计量单位，未将其自动相加"
        unit = measures[0].group(3).lower()
        minimum = sum(float(match.group(1)) for match in measures)
        maximum = sum(
            float(match.group(2) if match.group(2) is not None else match.group(1))
            for match in measures
        )
        if any(
            match.group(2) is not None and float(match.group(2)) < float(match.group(1))
            for match in measures
        ):
            raise ValueError("Ingredient amount range is reversed")
        if unit in {"g", "克", "kg", "千克", "斤"}:
            factor = 1000 if unit in {"kg", "千克"} else 500 if unit == "斤" else 1
            minimum, maximum = minimum * factor, maximum * factor
            note = "菜谱明确克重；按所列可食原料状态计算" + ("，同原料分阶段克数相加" if len(measures) > 1 else "")
        else:
            if alias.volume_portion_modifier is None or alias.volume_portion_ml is None:
                return None, None, "毫升无同食品官方份量换算依据，未按1mL=1g计算"
            portion = _portion(food, alias.volume_portion_modifier)
            volume = alias.volume_portion_ml * portion["amount"]
            factor = portion["gram_weight"] / volume * (1000 if unit in {"l", "升"} else 1)
            minimum, maximum = minimum * factor, maximum * factor
            note = f"近似换算：官方{portion['amount']} {portion['modifier']} = {portion['gram_weight']}g；量具口径{alias.volume_portion_ml}mL/单位"
    else:
        count_text = re.split(r"[;；]|不擅改|不可|不能|不应|不是", text, maxsplit=1)[0]
        counts = list(_COUNTS.finditer(count_text))
        if len(counts) != 1 or alias.count_portion_modifier is None:
            return None, None, "件数/中式量具缺乏对应的官方单件重量，未猜测克数"
        if alias.count_portion_modifier == "clove" and counts[0].group(3) != "瓣":
            return None, None, "蒜头、蒜片和蒜瓣不是同一份量，未将其按瓣数换算"
        portion = _portion(food, alias.count_portion_modifier)
        count = counts[0]
        minimum = float(count.group(1)) * portion["gram_weight"] / portion["amount"]
        maximum = (
            float(count.group(2) if count.group(2) is not None else count.group(1))
            * portion["gram_weight"]
            / portion["amount"]
        )
        note = f"大小假设：按官方{portion['amount']} {portion['modifier']} = {portion['gram_weight']}g可食部近似换算；实际大小可能不同"
    if maximum < minimum:
        raise ValueError("Ingredient amount range is reversed")
    if re.search(r"可选|选配|可不放|可省|不放|省略", text):
        minimum = 0.0
        note += "；可选原料按0至所列上限计算"
    return round(minimum, 6), round(maximum, 6), note


def _ingredient_fact(
    ingredient: dict,
    food: dict | None,
    alias: FoodAlias | None,
    override: IngredientOverride | None,
    reason: str,
) -> IngredientNutrition:
    """无可计算克重时仍补实际官方原料资料，避免整项仅贴缺失标签。"""
    amount = ingredient["amount"]
    if food is None:
        return IngredientNutrition(
            name=ingredient["name"],
            amount_text=amount,
            status="unmatched",
            match_note=reason,
            quantity_note=reason,
        )
    minimum, maximum, note = _quantity(amount, alias, food, override)
    values = {key: food["per_100g"].get(key) for key in NUTRIENTS}
    contribution = {}
    if minimum is not None and maximum is not None:
        contribution = {
            key: NutrientRange(
                minimum=None if value is None else round(minimum / 100 * value, 4),
                maximum=None if value is None else round(maximum / 100 * value, 4),
            )
            for key, value in values.items()
        }
    return IngredientNutrition(
        name=ingredient["name"],
        amount_text=amount,
        status="calculated" if minimum is not None else "reference_only",
        food_key=food["key"],
        official_description=food["official_description"],
        source_url=food["source_url"],
        source_food_id=food["source_food_id"],
        state=food["state"],
        match_note=reason,
        per_100g=values,
        grams_min=minimum,
        grams_max=maximum,
        quantity_note=note,
        contribution=contribution,
    )


def _subtotal(facts: list[IngredientNutrition]) -> dict[str, NutrientSubtotal]:
    """按营养素分别加已知值，未知值从不自动视作零。"""
    result = {}
    calculated = [fact for fact in facts if fact.status == "calculated"]
    for key in NUTRIENTS:
        included = [fact for fact in calculated if fact.contribution[key].minimum is not None]
        result[key] = NutrientSubtotal(
            minimum=round(
                sum(
                    value
                    for fact in included
                    if (value := fact.contribution[key].minimum) is not None
                ),
                2,
            )
            if included
            else None,
            maximum=round(
                sum(
                    value
                    for fact in included
                    if (value := fact.contribution[key].maximum) is not None
                ),
                2,
            )
            if included
            else None,
            included_ingredients=[fact.name for fact in included],
            missing_values_for=[
                fact.name for fact in calculated if fact.contribution[key].minimum is None
            ],
        )
    return result


def apply_recipe_nutrition(
    records: list[dict], profiles_path: Path | None, matches_path: Path | None
) -> tuple[list[dict], dict]:
    """只补已审查修订的菜谱，绑定官方成分表和匹配配置的摘要。"""
    if not any(record.get("curation") is not None for record in records):
        return records, {"enriched_recipes": 0, "source_files": []}
    if profiles_path is None or matches_path is None:
        raise ValueError(
            "Curated recipes require official nutrition profiles and ingredient matches"
        )
    profiles_bytes, matches_bytes = profiles_path.read_bytes(), matches_path.read_bytes()
    profiles = json.loads(profiles_bytes)
    matches = IngredientMatches.model_validate_json(matches_bytes)
    foods = {food["key"]: food for food in profiles["foods"]}
    if len(foods) != len(profiles["foods"]):
        raise ValueError("Duplicate official food key")
    aliases: dict[str, FoodAlias] = {}
    for alias_entry in matches.aliases:
        if alias_entry.food_key not in foods:
            raise ValueError(f"Unknown official food key: {alias_entry.food_key}")
        for name in alias_entry.names:
            if _name(name) in aliases:
                raise ValueError(f"Duplicate food alias: {name}")
            aliases[_name(name)] = alias_entry
    exclusions = {
        _name(name): item.reason for item in matches.exclusion_names for name in item.names
    }
    overrides = {(item.row, _name(item.ingredient_name)): item for item in matches.row_overrides}
    if len(overrides) != len(matches.row_overrides):
        raise ValueError("Duplicate row ingredient override")
    for override_entry in matches.row_overrides:
        if override_entry.food_key is not None and override_entry.food_key not in foods:
            raise ValueError(f"Unknown override food key: {override_entry.food_key}")
    references = {item.row: item for item in matches.recipe_reference_foods}
    if len(references) != len(matches.recipe_reference_foods):
        raise ValueError("Duplicate recipe reference foods row")
    for reference in matches.recipe_reference_foods:
        if any(key not in foods for key in reference.food_keys):
            raise ValueError("Unknown recipe reference food key")
    profile_sha, matches_sha = (
        hashlib.sha256(profiles_bytes).hexdigest(),
        hashlib.sha256(matches_bytes).hexdigest(),
    )
    updated = []
    statuses: Counter[str] = Counter()
    scopes: Counter[str] = Counter()
    details = []
    for original in records:
        if original.get("curation") is None:
            updated.append(original)
            continue
        record = copy.deepcopy(original)
        row = record["curation"]["audit_row"]
        facts = []
        for ingredient in record["ingredients"]:
            name = _name(ingredient["name"])
            alias = aliases.get(name)
            override = overrides.get((row, name))
            if override is not None:
                key, reason = override.food_key, override.reason
            elif name in exclusions:
                key, reason = None, exclusions[name]
            elif alias is not None:
                key, reason = alias.food_key, alias.match_note
            else:
                key, reason = None, "尚无与该物种、加工状态和规格匹配的官方成分；需产品标签或可食部资料"
            facts.append(
                _ingredient_fact(
                    ingredient, None if key is None else foods[key], alias, override, reason
                )
            )
        counted = sum(fact.status == "calculated" for fact in facts)
        scope: Literal[
            "listed_input_total", "known_input_subtotal", "ingredient_reference_only"
        ] = (
            "listed_input_total"
            if counted == len(facts)
            else "known_input_subtotal"
            if counted
            else "ingredient_reference_only"
        )
        reference_foods = []
        if row in references:
            reference = references[row]
            reference_foods = [
                _ingredient_fact(
                    {"name": foods[key]["official_description"], "amount": None},
                    foods[key],
                    None,
                    None,
                    reference.reason,
                )
                for key in reference.food_keys
            ]
        available_nutrients = {
            nutrient
            for fact in facts + reference_foods
            for nutrient, value in fact.per_100g.items()
            if value is not None and value > 0
        }
        notes = [
            NutritionNote(
                statement=note["statement_zh"], source_url=note["source_url"], scope=note["scope"]
            )
            for note in profiles["nutrient_functions"]
            if available_nutrients.intersection(note["nutrients"])
        ]
        nutrition = RecipeNutrition(
            method="official_food_composition_input_calculation",
            scope=scope,
            basis="整批所列原料的已知用量；不是每份、每100g成菜或实际摄入量",
            profiles_sha256=profile_sha,
            matches_sha256=matches_sha,
            ingredients=facts,
            not_in_subtotal=[fact.name for fact in facts if fact.status != "calculated"],
            reference_foods=reference_foods,
            subtotal=_subtotal(facts),
            nutrient_notes=notes,
            interpretation=[
                "官方食物成分是对应食品状态的参考平均值；件数换算和品牌差异见各原料说明。",
                "未计入原料、油炸吸油、弃汤弃渣及烹调酒精保留量会影响结果；小计不能冒充整菜热量。",
                "不以未知成菜重量换算每100g；营养素一般作用不等于本菜的治疗或保健功效。",
            ],
        )
        record["nutrition"] = nutrition.model_dump()
        updated.append(record)
        statuses.update(fact.status for fact in facts)
        scopes[scope] += 1
        details.append(
            {
                "id": record["id"],
                "row": row,
                "name": record["name"],
                "scope": scope,
                "calculated_ingredients": counted,
                "reference_ingredients": sum(fact.food_key is not None for fact in facts),
            }
        )
    return updated, {
        "enriched_recipes": len(details),
        "ingredient_statuses": dict(statuses),
        "calculation_scopes": dict(scopes),
        "source_files": [
            {"path": profiles_path.resolve().as_posix(), "sha256": profile_sha},
            {"path": matches_path.resolve().as_posix(), "sha256": matches_sha},
        ],
        "recipes": details,
    }


def apply_nutrition_registry(records: list[dict], registry_path: Path) -> tuple[list[dict], dict]:
    """按修订批次分别计算，再按原顺序合并，保留各批次证据版本。"""
    grouped: dict[str, list[dict]] = {}
    for record in records:
        if record.get("curation") is not None:
            grouped.setdefault(record["curation"]["batch_id"], []).append(record)
    if not grouped:
        return records, {"enriched_recipes": 0, "source_files": []}
    body = registry_path.read_bytes()
    registry = NutritionRegistry.model_validate_json(body)
    registered_ids = [batch.id for batch in registry.batches]
    if len(registered_ids) != len(set(registered_ids)):
        raise ValueError("Duplicate nutrition batch identity")
    unregistered = set(grouped) - set(registered_ids)
    if unregistered:
        raise ValueError(f"Nutrition has unregistered correction batches: {sorted(unregistered)}")
    by_id = {record["id"]: record for record in records}
    if len(by_id) != len(records):
        raise ValueError("Duplicate recipe identity in nutrition input")
    base = registry_path.resolve().parent
    source_files = [
        {"path": registry_path.resolve().as_posix(), "sha256": hashlib.sha256(body).hexdigest()}
    ]
    batch_reports = []
    details = []
    statuses: Counter[str] = Counter()
    scopes: Counter[str] = Counter()
    for batch in registry.batches:
        if batch.id not in grouped:
            continue
        profiles_path, matches_path = (
            (base / value).resolve() for value in (batch.profiles, batch.matches)
        )
        if not profiles_path.is_relative_to(base) or not matches_path.is_relative_to(base):
            raise ValueError("Nutrition evidence path escapes its registered directory")
        updated, report = apply_recipe_nutrition(grouped[batch.id], profiles_path, matches_path)
        by_id.update((record["id"], record) for record in updated)
        source_files.extend(report["source_files"])
        statuses.update(report["ingredient_statuses"])
        scopes.update(report["calculation_scopes"])
        details.extend(report["recipes"])
        batch_reports.append({"id": batch.id, **report})
    return [by_id[record["id"]] for record in records], {
        "enriched_recipes": len(details),
        "ingredient_statuses": dict(statuses),
        "calculation_scopes": dict(scopes),
        "source_files": source_files,
        "registry_path": registry_path.resolve().as_posix(),
        "batches": batch_reports,
        "recipes": sorted(details, key=lambda row: row["row"]),
    }
