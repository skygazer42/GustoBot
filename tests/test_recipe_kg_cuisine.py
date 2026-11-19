"""
Regression tests for cuisine-oriented recipe graph support.
"""

import json
from pathlib import Path

K_MAIN = "\u4e3b\u6599"
K_AUX = "\u8f85\u6599"
K_TIME = "\u8017\u65f6"
K_FLAVOR = "\u53e3\u5473"
K_METHOD = "\u5de5\u827a"
K_TYPE = "\u7c7b\u578b"
K_CUISINE = "\u83dc\u7cfb"
K_INSTRUCTIONS = "\u505a\u6cd5"


def _write_recipe_fixture(path: Path) -> None:
    payload = {
        "\u4e5d\u8f6c\u5927\u80a0": {
            K_MAIN: [["\u732a\u5927\u80a0", "500g"]],
            K_AUX: [["\u8471", "\u5c11\u8bb8"]],
            K_TIME: "30\u5206\u949f",
            K_FLAVOR: "\u9178\u751c,\u54b8\u9c9c",
            K_METHOD: "\u70e7",
            K_TYPE: "\u70ed\u83dc",
            K_CUISINE: "\u9c81\u83dc",
            K_INSTRUCTIONS: "1:\u5904\u7406\u98df\u6750\u30022:\u8c03\u5473\u6536\u6c41\u3002",
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_recipe_json_parser_keeps_cuisine_styles(tmp_path: Path) -> None:
    from gustobot.infrastructure.knowledge.recipe_catalog import (
        load_recipe_records,
    )

    recipe_path = tmp_path / "recipe.json"
    _write_recipe_fixture(recipe_path)

    records, ingredients_used = load_recipe_records(recipe_path)

    assert len(records) == 1
    assert records[0].name == "\u4e5d\u8f6c\u5927\u80a0"
    assert records[0].cuisine_styles == ["\u9c81\u83dc"]
    assert "\u732a\u5927\u80a0" in ingredients_used


def test_recipe_csv_assets_include_cuisine_nodes_and_relationships(tmp_path: Path) -> None:
    from gustobot.infrastructure.knowledge.recipe_catalog import (
        load_recipe_records,
    )
    from scripts.recipe_kg_to_csv import _build_graph_assets

    recipe_path = tmp_path / "recipe.json"
    _write_recipe_fixture(recipe_path)

    records, _ = load_recipe_records(recipe_path)
    assets = _build_graph_assets(records, [])

    assert "nodes_cuisine" in assets
    assert "rel_cuisine" in assets
    assert assets["nodes_cuisine"] == [
        {"id": "cuisine_1", "name": "\u9c81\u83dc"},
    ]
    assert assets["rel_cuisine"] == [
        {"start": "dish_1", "end": "cuisine_1"},
    ]
