#!/usr/bin/env python3
"""Convert recipe JSON datasets into Neo4j-admin compatible CSV files."""

import argparse
import csv
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gustobot.infrastructure.knowledge.recipe_catalog import (
    IngredientProfile,
    RecipeRecord,
    load_ingredient_profiles,
    load_recipe_records,
)


def main() -> None:
    args = _parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    recipes, ingredients_used = load_recipe_records(args.recipe_json)
    profiles = load_ingredient_profiles(args.ingredient_json, ingredients_used)

    if not recipes:
        raise SystemExit("No recipes parsed from JSON; aborting CSV generation.")

    assets = _build_graph_assets(recipes, profiles)
    _write_csv(output_dir, assets)
    print(f"Generated Neo4j CSV files in {output_dir}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Neo4j CSV import files from recipe JSON data."
    )
    parser.add_argument(
        "--recipe-json",
        type=Path,
        default=Path("data/recipe.json"),
        help="Path to the recipe dataset JSON file.",
    )
    parser.add_argument(
        "--ingredient-json",
        type=Path,
        default=Path("data/excipients.json"),
        help="Path to the ingredient nutrition JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where generated CSV files will be written.",
    )
    return parser.parse_args()


def _build_graph_assets(
    recipes: list["RecipeRecord"],
    profiles: list["IngredientProfile"],
) -> dict[str, list[dict[str, object]]]:
    dish_registry: dict[str, dict[str, object]] = {}
    ingredient_registry: dict[str, dict[str, object]] = {}
    flavor_registry: dict[str, dict[str, object]] = {}
    method_registry: dict[str, dict[str, object]] = {}
    type_registry: dict[str, dict[str, object]] = {}
    cuisine_registry: dict[str, dict[str, object]] = {}
    step_registry: dict[str, dict[str, object]] = {}
    nutrition_registry: dict[str, dict[str, object]] = {}
    benefit_registry: dict[str, dict[str, object]] = {}

    dishes: list[dict[str, object]] = []
    ingredients: list[dict[str, object]] = []
    flavors: list[dict[str, object]] = []
    methods: list[dict[str, object]] = []
    dish_types: list[dict[str, object]] = []
    cuisines: list[dict[str, object]] = []
    steps: list[dict[str, object]] = []
    nutrition_nodes: list[dict[str, object]] = []
    benefit_nodes: list[dict[str, object]] = []

    rel_main: list[dict[str, object]] = []
    rel_aux: list[dict[str, object]] = []
    rel_flavor: list[dict[str, object]] = []
    rel_method: list[dict[str, object]] = []
    rel_type: list[dict[str, object]] = []
    rel_cuisine: list[dict[str, object]] = []
    rel_step: list[dict[str, object]] = []
    rel_nutrition: list[dict[str, object]] = []
    rel_benefit: list[dict[str, object]] = []

    def _ensure_node(
        registry: dict[str, dict[str, object]],
        name: str,
        prefix: str,
        collection: list[dict[str, object]],
    ) -> dict[str, object]:
        node = registry.get(name)
        if node is None:
            node = {"id": f"{prefix}_{len(registry) + 1}", "name": name}
            registry[name] = node
            collection.append(node)
        return node

    for recipe in recipes:
        dish_node = _ensure_node(dish_registry, recipe.name, "dish", dishes)
        dish_node.update(
            {
                "cook_time": recipe.cook_time or "",
                "instructions": recipe.instructions or "",
            },
        )
        dish_id = dish_node["id"]

        for ingredient in recipe.main_ingredients:
            ingredient_node = _ensure_node(
                ingredient_registry, ingredient.name, "ingredient", ingredients
            )
            rel_main.append(
                {
                    "start": dish_id,
                    "end": ingredient_node["id"],
                    "amount_text": ingredient.amount or "",
                },
            )

        for ingredient in recipe.aux_ingredients:
            ingredient_node = _ensure_node(
                ingredient_registry, ingredient.name, "ingredient", ingredients
            )
            rel_aux.append(
                {
                    "start": dish_id,
                    "end": ingredient_node["id"],
                    "amount_text": ingredient.amount or "",
                },
            )

        for flavor in recipe.flavors:
            flavor_node = _ensure_node(flavor_registry, flavor, "flavor", flavors)
            rel_flavor.append({"start": dish_id, "end": flavor_node["id"]})

        for method in recipe.methods:
            method_node = _ensure_node(method_registry, method, "method", methods)
            rel_method.append({"start": dish_id, "end": method_node["id"]})

        for dtype in recipe.dish_types:
            type_node = _ensure_node(type_registry, dtype, "dtype", dish_types)
            rel_type.append({"start": dish_id, "end": type_node["id"]})

        for cuisine in recipe.cuisine_styles:
            cuisine_node = _ensure_node(cuisine_registry, cuisine, "cuisine", cuisines)
            rel_cuisine.append({"start": dish_id, "end": cuisine_node["id"]})

        for step in recipe.steps:
            step_key = f"{dish_id}_{step.order}"
            if step_key not in step_registry:
                step_registry[step_key] = {
                    "id": f"step_{len(step_registry) + 1}",
                    "name": f"{recipe.name} - Step {step.order}",
                    "dish_name": recipe.name,
                    "order": step.order,
                    "instruction": step.instruction,
                }
                steps.append(step_registry[step_key])
            rel_step.append(
                {
                    "start": dish_id,
                    "end": step_registry[step_key]["id"],
                    "order": step.order,
                },
            )

    for profile in profiles:
        profile_node = ingredient_registry.get(profile.name)
        if profile_node is None:
            continue
        ingredient_id = profile_node["id"]

        if profile.nutrition:
            if profile.name not in nutrition_registry:
                nutrition_registry[profile.name] = {
                    "id": f"nutrition_{len(nutrition_registry) + 1}",
                    "name": profile.name,
                    "description": profile.nutrition,
                }
                nutrition_nodes.append(nutrition_registry[profile.name])
            rel_nutrition.append(
                {
                    "start": ingredient_id,
                    "end": nutrition_registry[profile.name]["id"],
                },
            )

        for benefit in profile.benefits:
            benefit_node = benefit_registry.get(benefit)
            if benefit_node is None:
                checksum = hashlib.sha1(benefit.encode("utf-8"), usedforsecurity=False).hexdigest()[
                    :12
                ]
                benefit_node = {
                    "id": f"benefit_{len(benefit_registry) + 1}_{checksum}",
                    "name": benefit,
                }
                benefit_registry[benefit] = benefit_node
                benefit_nodes.append(benefit_node)
            rel_benefit.append(
                {
                    "start": ingredient_id,
                    "end": benefit_node["id"],
                },
            )

    return {
        "nodes_dish": dishes,
        "nodes_ingredient": ingredients,
        "nodes_flavor": flavors,
        "nodes_method": methods,
        "nodes_type": dish_types,
        "nodes_cuisine": cuisines,
        "nodes_step": steps,
        "nodes_nutrition": nutrition_nodes,
        "nodes_benefit": benefit_nodes,
        "rel_main": rel_main,
        "rel_aux": rel_aux,
        "rel_flavor": rel_flavor,
        "rel_method": rel_method,
        "rel_type": rel_type,
        "rel_cuisine": rel_cuisine,
        "rel_step": rel_step,
        "rel_nutrition": rel_nutrition,
        "rel_benefit": rel_benefit,
    }


def _write_csv(output_dir: Path, assets: dict[str, list[dict[str, object]]]) -> None:
    writers = {
        "nodes_dish": (
            "dish_nodes.csv",
            ["id:ID(Dish)", "name", "cook_time", "instructions"],
        ),
        "nodes_ingredient": (
            "ingredient_nodes.csv",
            ["id:ID(Ingredient)", "name"],
        ),
        "nodes_flavor": (
            "flavor_nodes.csv",
            ["id:ID(Flavor)", "name"],
        ),
        "nodes_method": (
            "method_nodes.csv",
            ["id:ID(CookingMethod)", "name"],
        ),
        "nodes_type": (
            "type_nodes.csv",
            ["id:ID(DishType)", "name"],
        ),
        "nodes_cuisine": ("cuisine_nodes.csv", ["id:ID(CuisineStyle)", "name"]),
        "nodes_step": (
            "step_nodes.csv",
            ["id:ID(CookingStep)", "name", "dish_name", "order:int", "instruction"],
        ),
        "nodes_nutrition": (
            "nutrition_nodes.csv",
            ["id:ID(NutritionProfile)", "name", "description"],
        ),
        "nodes_benefit": (
            "benefit_nodes.csv",
            ["id:ID(HealthBenefit)", "name"],
        ),
        "rel_main": (
            "rel_has_main.csv",
            [":START_ID(Dish)", ":END_ID(Ingredient)", "amount_text"],
        ),
        "rel_aux": (
            "rel_has_aux.csv",
            [":START_ID(Dish)", ":END_ID(Ingredient)", "amount_text"],
        ),
        "rel_flavor": (
            "rel_has_flavor.csv",
            [":START_ID(Dish)", ":END_ID(Flavor)"],
        ),
        "rel_method": (
            "rel_uses_method.csv",
            [":START_ID(Dish)", ":END_ID(CookingMethod)"],
        ),
        "rel_type": (
            "rel_belongs_type.csv",
            [":START_ID(Dish)", ":END_ID(DishType)"],
        ),
        "rel_cuisine": (
            "rel_belongs_cuisine.csv",
            [":START_ID(Dish)", ":END_ID(CuisineStyle)"],
        ),
        "rel_step": (
            "rel_has_step.csv",
            [":START_ID(Dish)", ":END_ID(CookingStep)", "order:int"],
        ),
        "rel_nutrition": (
            "rel_has_nutrition.csv",
            [":START_ID(Ingredient)", ":END_ID(NutritionProfile)"],
        ),
        "rel_benefit": (
            "rel_has_benefit.csv",
            [":START_ID(Ingredient)", ":END_ID(HealthBenefit)"],
        ),
    }

    for key, (filename, headers) in writers.items():
        rows = assets[key]
        path = output_dir / filename
        with path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(
                fp,
                fieldnames=headers,
                extrasaction="ignore",
                quoting=csv.QUOTE_ALL,
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(_encode_row(headers, row))


def _encode_row(headers: list[str], row: dict[str, object]) -> dict[str, object]:
    encoded: dict[str, object] = {}
    for header in headers:
        key = header
        if header.startswith(":START_ID"):
            key = "start"
        elif header.startswith(":END_ID"):
            key = "end"
        elif header.endswith(":int") or ":ID" in header:
            key = header.split(":")[0]
        value = row[key]
        encoded[header] = value if value is not None else ""
    return encoded


if __name__ == "__main__":
    main()
