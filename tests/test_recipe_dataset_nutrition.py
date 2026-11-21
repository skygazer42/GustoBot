"""营养补全必须可复算，不能把未知、骨重或油锅投料算成摄入量。"""

import json
from pathlib import Path

import pytest

from scripts.recipe_dataset_nutrition import (
    apply_nutrition_registry,
    apply_recipe_nutrition,
)


def nutrition_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """用已知值建立独立成分表，隔离网络和真实资料的后续更新。"""
    profiles = {
        "foods": [
            {
                "key": key,
                "official_description": key,
                "source_url": "https://example.org/" + key,
                "source_food_id": key,
                "state": state,
                "per_100g": values,
                "portions": portions,
            }
            for key, state, values, portions in [
                (
                    "egg",
                    "raw_edible",
                    {"energy_kcal": 143.0, "protein_g": 12.56, "fiber_g": 0.0},
                    [{"modifier": "large", "amount": 1.0, "gram_weight": 50.0}],
                ),
                (
                    "oil",
                    "oil",
                    {"energy_kcal": 884.0, "protein_g": 0.0, "fiber_g": 0.0},
                    [{"modifier": "tbsp", "amount": 1.0, "gram_weight": 13.6}],
                ),
                ("rice_dry", "dry", {"energy_kcal": 360.0, "protein_g": None, "fiber_g": 0.0}, []),
                (
                    "rice_cooked",
                    "cooked",
                    {"energy_kcal": 130.0, "protein_g": 2.0, "fiber_g": 0.0},
                    [],
                ),
                (
                    "erythritol",
                    "pure",
                    {"energy_kcal": 0.0, "protein_g": None, "fiber_g": None},
                    [],
                ),
            ]
        ],
        "sources": [],
        "nutrient_functions": [],
    }
    matches = {
        "schema_version": 1,
        "aliases": [
            {
                "names": ["鸡蛋"],
                "food_key": "egg",
                "match_note": "按大号鸡蛋作近似参考",
                "count_portion_modifier": "large",
            },
            {
                "names": ["熟豆油"],
                "food_key": "oil",
                "match_note": "豆油参考",
                "volume_portion_modifier": "tbsp",
                "volume_portion_ml": 15.0,
            },
            {"names": ["生米"], "food_key": "rice_dry", "match_note": "干重"},
            {"names": ["熟米饭"], "food_key": "rice_cooked", "match_note": "熟重"},
            {"names": ["赤藓糖醇"], "food_key": "erythritol", "match_note": "纯品FDA系数"},
        ],
        "row_overrides": [],
        "exclusion_names": [{"names": ["带骨鸡腿"], "reason": "采购重量不等于可食部"}],
    }
    profile_path, match_path = tmp_path / "profiles.json", tmp_path / "matches.json"
    profile_path.write_text(json.dumps(profiles), encoding="utf-8")
    match_path.write_text(json.dumps(matches), encoding="utf-8")
    return profile_path, match_path


def recipe(*ingredients: tuple[str, str | None], row: int = 1, curated: bool = True) -> dict:
    """构造只包含营养补全所需契约的菜谱。"""
    record: dict = {
        "id": f"recipe:{row}",
        "name": "测试菜",
        "ingredients": [{"name": name, "amount": amount} for name, amount in ingredients],
        "servings": "1人份",
    }
    if curated:
        record["curation"] = {"audit_row": row}
    return record


def test_counts_and_milliliters_use_same_food_official_portion(tmp_path: Path) -> None:
    """个数和毫升有明确份量依据，不能一律按一毫升一克。"""
    paths = nutrition_fixture(tmp_path)
    records, report = apply_recipe_nutrition([recipe(("鸡蛋", "2个"), ("熟豆油", "15ml"))], *paths)
    nutrition = records[0]["nutrition"]
    egg, oil = nutrition["ingredients"]
    assert egg["grams_min"] == 100.0
    assert oil["grams_min"] == 13.6
    assert "large" in egg["quantity_note"]
    assert nutrition["subtotal"]["energy_kcal"]["minimum"] == pytest.approx(263.2, abs=0.1)
    assert nutrition["scope"] == "listed_input_total"
    assert report["enriched_recipes"] == 1


def test_ranges_and_optional_ingredients_preserve_uncertainty(tmp_path: Path) -> None:
    """范围上下界逐项相加，可选原料下界为零。"""
    paths = nutrition_fixture(tmp_path)
    records, _ = apply_recipe_nutrition(
        [recipe(("生米", "100-150g"), ("鸡蛋", "1个（可选）"))], *paths
    )
    total = records[0]["nutrition"]["subtotal"]["energy_kcal"]
    assert total["minimum"] == 360.0
    assert total["maximum"] == 611.5


def test_missing_value_is_not_zero_and_subtotal_is_not_whole_recipe(tmp_path: Path) -> None:
    """缺失营养值和未计入食材留在计算口径中，不伪造完整总量。"""
    paths = nutrition_fixture(tmp_path)
    records, _ = apply_recipe_nutrition(
        [recipe(("生米", "100g"), ("鸡蛋", "1个"), ("调味包", None))], *paths
    )
    nutrition = records[0]["nutrition"]
    assert nutrition["scope"] == "known_input_subtotal"
    protein = nutrition["subtotal"]["protein_g"]
    assert protein["minimum"] == 6.28
    assert protein["missing_values_for"] == ["生米"]
    assert nutrition["ingredients"][-1]["status"] == "unmatched"
    assert nutrition["not_in_subtotal"] == ["调味包"]


def test_dry_and_cooked_foods_are_not_interchangeable(tmp_path: Path) -> None:
    """同为一百克，干米和熟饭必须匹配各自数据。"""
    paths = nutrition_fixture(tmp_path)
    records, _ = apply_recipe_nutrition(
        [recipe(("生米", "100g")), recipe(("熟米饭", "100g"), row=2)], *paths
    )
    assert [r["nutrition"]["subtotal"]["energy_kcal"]["minimum"] for r in records] == [360.0, 130.0]


def test_bone_weight_and_deep_frying_oil_are_not_eaten_weight(tmp_path: Path) -> None:
    """即使数字明确，带骨采购量和油浴量也不进入营养小计。"""
    paths = nutrition_fixture(tmp_path)
    records, _ = apply_recipe_nutrition(
        [recipe(("带骨鸡腿", "500g"), ("熟豆油", "500ml（油炸用）"), ("鸡蛋", "1个"))], *paths
    )
    nutrition = records[0]["nutrition"]
    assert nutrition["ingredients"][1]["status"] == "reference_only"
    assert nutrition["subtotal"]["energy_kcal"]["minimum"] == 71.5


def test_unknown_household_measure_and_formula_are_not_evaluated(tmp_path: Path) -> None:
    """中式勺和份数公式没有实际数值，不猜换算。"""
    paths = nutrition_fixture(tmp_path)
    records, _ = apply_recipe_nutrition([recipe(("熟豆油", "一勺"), ("生米", "份数*100g"))], *paths)
    assert all(
        item["status"] == "reference_only" for item in records[0]["nutrition"]["ingredients"]
    )
    assert records[0]["nutrition"]["subtotal"]["energy_kcal"]["minimum"] is None


def test_zero_energy_is_preserved_without_inventing_macronutrients(tmp_path: Path) -> None:
    """纯赤藓糖醇的零能量不应被判空，也不能反推其营养成分。"""
    paths = nutrition_fixture(tmp_path)
    records, _ = apply_recipe_nutrition([recipe(("赤藓糖醇", "40g"))], *paths)
    assert records[0]["nutrition"]["subtotal"]["energy_kcal"]["minimum"] == 0.0
    assert records[0]["nutrition"]["subtotal"]["protein_g"]["minimum"] is None


def test_only_curated_records_are_enriched_and_result_is_reproducible(tmp_path: Path) -> None:
    """既有非目标行完全不变，重复计算得到相同内容。"""
    paths = nutrition_fixture(tmp_path)
    original = recipe(("鸡蛋", "1个"), row=51, curated=False)
    records, _ = apply_recipe_nutrition([recipe(("鸡蛋", "1个")), original], *paths)
    repeated, _ = apply_recipe_nutrition(records, *paths)
    assert records == repeated
    assert records[1] == original and "nutrition" not in original


def test_portion_amount_is_part_of_conversion(tmp_path: Path) -> None:
    """份量表若写两枚共一百克，不能误读为每枚一百克。"""
    profile_path, match_path = nutrition_fixture(tmp_path)
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    payload["foods"][0]["portions"][0].update(amount=2.0, gram_weight=100.0)
    profile_path.write_text(json.dumps(payload), encoding="utf-8")
    records, _ = apply_recipe_nutrition([recipe(("鸡蛋", "1个"))], profile_path, match_path)
    assert records[0]["nutrition"]["ingredients"][0]["grams_min"] == 50.0


def test_conflicting_aliases_fail_instead_of_picking_arbitrary_food(tmp_path: Path) -> None:
    """精确别名不能静默映射两个生熟状态。"""
    profile_path, match_path = nutrition_fixture(tmp_path)
    payload = json.loads(match_path.read_text(encoding="utf-8"))
    payload["aliases"].append({"names": ["生米"], "food_key": "rice_cooked", "match_note": "冲突"})
    match_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        apply_recipe_nutrition([recipe(("生米", "100g"))], profile_path, match_path)


def test_total_and_its_stage_allocation_are_not_double_counted(tmp_path: Path) -> None:
    """量表的总重后再解释分配，不代表额外加入相同的重量。"""
    paths = nutrition_fixture(tmp_path)
    records, _ = apply_recipe_nutrition(
        [recipe(("生米", "250g：第一阶段100g，第二阶段150g"))], *paths
    )
    assert records[0]["nutrition"]["ingredients"][0]["grams_min"] == 250.0
    records, _ = apply_recipe_nutrition(
        [recipe(("生米", "总量150-200g（第一阶段100g，其余50-100g）"))], *paths
    )
    assert records[0]["nutrition"]["ingredients"][0]["grams_min"] == 150.0
    assert records[0]["nutrition"]["ingredients"][0]["grams_max"] == 200.0


def test_one_sided_amount_does_not_become_an_exact_figure(tmp_path: Path) -> None:
    """至少或不超过没有闭合范围，不把其中数字误当实际投料。"""
    paths = nutrition_fixture(tmp_path)
    records, _ = apply_recipe_nutrition([recipe(("熟豆油", "至少30ml"))], *paths)
    assert records[0]["nutrition"]["ingredients"][0]["status"] == "reference_only"


def test_negated_conversion_and_garlic_heads_are_not_counted_as_cloves(tmp_path: Path) -> None:
    """真实蒜片记录的否定说明不是正向用量，蒜头也不是蒜瓣。"""
    profiles_path, matches_path = nutrition_fixture(tmp_path)
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    profiles["foods"].append(
        {
            "key": "garlic",
            "official_description": "Garlic, raw",
            "source_food_id": "garlic",
            "source_url": "https://example.org/garlic",
            "state": "raw_edible",
            "per_100g": {"energy_kcal": 149.0},
            "portions": [{"modifier": "clove", "amount": 1.0, "gram_weight": 3.0}],
        }
    )
    profiles_path.write_text(json.dumps(profiles), encoding="utf-8")
    matches = json.loads(matches_path.read_text(encoding="utf-8"))
    matches["aliases"].append(
        {
            "names": ["蒜"],
            "food_key": "garlic",
            "match_note": "仅蒜瓣可换算",
            "count_portion_modifier": "clove",
        }
    )
    matches_path.write_text(json.dumps(matches), encoding="utf-8")
    for amount in ["2片；保留原文切片单位，不擅改为2瓣", "2头"]:
        records, _ = apply_recipe_nutrition([recipe(("蒜", amount))], profiles_path, matches_path)
        assert records[0]["nutrition"]["ingredients"][0]["status"] == "reference_only"


def test_nutrition_batches_keep_published_recipe_values_unchanged(tmp_path: Path) -> None:
    """后续批次补成分资料时，已发布批次的数值和证据摘要保持原样。"""
    root = tmp_path / "nutrition"
    root.mkdir()
    first_profiles, first_matches = nutrition_fixture(root)
    second = root / "second"
    second.mkdir()
    second_profiles, _second_matches = nutrition_fixture(second)
    registry = root / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "batches": [
                    {"id": "first", "profiles": first_profiles.name, "matches": first_matches.name},
                    {
                        "id": "second",
                        "profiles": "second/profiles.json",
                        "matches": "second/matches.json",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    records = [recipe(("鸡蛋", "1个")), recipe(("鸡蛋", "1个"), row=51)]
    records[0]["curation"]["batch_id"] = "first"
    records[1]["curation"]["batch_id"] = "second"
    initial, report = apply_nutrition_registry(records, registry)
    payload = json.loads(second_profiles.read_text(encoding="utf-8"))
    payload["foods"][0]["per_100g"]["energy_kcal"] = 200.0
    second_profiles.write_text(json.dumps(payload), encoding="utf-8")
    updated, _ = apply_nutrition_registry(records, registry)
    assert initial[0] == updated[0]
    assert initial[1] != updated[1]
    assert updated[1]["nutrition"]["subtotal"]["energy_kcal"]["minimum"] == 100.0
    assert report["enriched_recipes"] == 2
    assert len(report["source_files"]) == 5
    assert [row["row"] for row in report["recipes"]] == [1, 51]


def test_nutrition_registry_requires_every_curated_batch(tmp_path: Path) -> None:
    """不把新批次静默套用旧批次的克重覆盖或营养匹配。"""
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema_version": 1, "batches": []}), encoding="utf-8")
    record = recipe(("鸡蛋", "1个"))
    record["curation"]["batch_id"] = "unregistered"
    with pytest.raises(ValueError, match="unregistered"):
        apply_nutrition_registry([record], registry)


def test_nutrition_registry_paths_cannot_escape_its_directory(tmp_path: Path) -> None:
    """注册表只允许其资料目录内的成分表与匹配文件。"""
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "batches": [
                    {"id": "first", "profiles": "../outside.json", "matches": "matches.json"}
                ],
            }
        ),
        encoding="utf-8",
    )
    record = recipe(("鸡蛋", "1个"))
    record["curation"]["batch_id"] = "first"
    with pytest.raises(ValueError, match="escapes"):
        apply_nutrition_registry([record], registry)
