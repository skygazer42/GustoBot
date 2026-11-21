"""验证扩充数据的事实保留、来源身份、去重边界与可导入契约。"""

import argparse
import copy
import io
import json
from pathlib import Path
from typing import cast

import pytest
from PIL import Image
from pydantic import ValidationError

from scripts import build_recipe_dataset as dataset
from scripts.recipe_dataset_http import DownloadCache


def meal_record(recipe_id: str = "123") -> dict:
    """构造最小但真实形状的 TheMealDB 响应，包含未知许可。"""
    return {
        "idMeal": recipe_id,
        "strMeal": "Pasta",
        "strInstructions": "Boil pasta at 18:00.\r\nAdd sauce and serve.",
        "strIngredient1": "Pasta",
        "strMeasure1": "100 g",
        "strIngredient2": "Salt",
        "strMeasure2": "",
        "strCategory": "Pasta",
        "strArea": "Italian",
        "strMealThumb": "https://www.themealdb.com/images/media/meals/pasta.jpg",
        "strSource": None,
        "strCreativeCommonsConfirmed": None,
    }


def test_openkg_preserves_aux_only_recipe_and_existing_cuisine() -> None:
    """主食材为空并不表示没有食材；保留已有西餐菜系与未知耗时。"""
    draft = dataset.normalize_openkg(
        "炖菜",
        {
            "主食材": [],
            "辅料": [["牛肉", "300克"], ["盐", 0]],
            "做法": "1:备料2:炖煮",
            "菜系": ["法国菜"],
            "耗时": "",
        },
        "a" * 64,
    )
    recipe = dataset.DatasetRecipe.model_validate(draft)
    assert [item.name for item in recipe.ingredients] == ["牛肉", "盐"]
    assert [item.role for item in recipe.ingredients] == ["aux", "aux"]
    assert recipe.ingredients[1].amount == "0"
    assert recipe.cuisines == ["法国菜"]
    assert recipe.durations.total is None
    assert recipe.steps == ["备料", "炖煮"]


def test_step_split_preserves_times_ratios_and_paragraphs() -> None:
    """时刻和配比不是编号，连续记录的步骤仍保持顺序。"""
    assert dataset.split_recorded_steps("1:18:00开始，水米比1:2。2:关火") == [
        "18:00开始，水米比1:2。",
        "关火",
    ]
    assert dataset.split_recorded_steps("Mix 1:2 sauce. Cook at 18:00.\nServe.") == [
        "Mix 1:2 sauce. Cook at 18:00.",
        "Serve.",
    ]


def test_step_split_does_not_consume_inline_ratio_as_step_two() -> None:
    """黑椒脆皮肠的真实比例写法不能截断第一步。"""
    text = "1:猪肉肥瘦比是1：9或者2：8；加入黑胡椒。2:大葱切细丝。3:搅拌。"
    assert dataset.split_recorded_steps(text) == [
        "猪肉肥瘦比是1：9或者2：8；加入黑胡椒。",
        "大葱切细丝。",
        "搅拌。",
    ]
    assert dataset.split_recorded_steps("1:按比例2:8；混合。2:加盐。3:烹煮。") == [
        "按比例2:8；混合。",
        "加盐。",
        "烹煮。",
    ]


def test_mealdb_retains_measures_language_and_unknown_rights() -> None:
    """图片链接和 CC 确认状态均不被冒称为已获具体商业许可。"""
    recipe = dataset.DatasetRecipe.model_validate(dataset.normalize_themealdb(meal_record()))
    assert recipe.language == "en"
    assert recipe.ingredients[0].amount == "100 g"
    assert recipe.ingredients[0].unit is None
    assert recipe.ingredients[1].amount is None
    assert recipe.images[0].license == "unknown"
    assert recipe.source.license_status == "development_only"
    assert recipe.durations.total is None
    assert recipe.source.original_url is None
    assert len(recipe.steps) == 2


def test_cc_confirmation_does_not_invent_license_version() -> None:
    """上游 Yes 只记录已确认标志，不能自行写成 CC BY 4.0。"""
    entry = meal_record()
    entry["strCreativeCommonsConfirmed"] = "Yes"
    recipe = dataset.DatasetRecipe.model_validate(dataset.normalize_themealdb(entry))
    assert recipe.images[0].license == "CC-confirmed-unspecified"
    assert recipe.images[0].license_status == "provider_confirmed"


def test_source_version_and_identity_are_stable_between_builds() -> None:
    """抓取时间不会使同一条来源反复获得新的内容身份。"""
    assert dataset.normalize_themealdb(meal_record()) == dataset.normalize_themealdb(meal_record())
    changed = meal_record()
    changed["strInstructions"] = "Cook differently."
    original = dataset.normalize_themealdb(meal_record())
    updated = dataset.normalize_themealdb(changed)
    assert original["id"] == updated["id"]
    assert original["source"]["revision"] != updated["source"]["revision"]


def test_exact_dedup_keeps_same_name_different_method() -> None:
    """相同标题的不同做法保留；完全相同内容合并并留住另一个出处。"""
    first = dataset.normalize_themealdb(meal_record("1"))
    duplicate = dataset.normalize_themealdb(meal_record("2"))
    variant = dataset.normalize_themealdb(meal_record("3"))
    variant["steps"] = ["Bake pasta instead."]
    recipes, rejected, duplicates = dataset.validate_recipes([first, duplicate, variant])
    assert not rejected
    assert len(recipes) == 2
    assert len(duplicates) == 1
    assert recipes[0].additional_sources[0].record_id == "2"
    assert len({recipe.content_sha256 for recipe in recipes}) == 2


def test_incomplete_recipe_is_reported_instead_of_silently_padded() -> None:
    """缺少烹饪步骤时拒绝该行，报告不泄漏整份输入。"""
    draft = dataset.normalize_themealdb(meal_record())
    draft["steps"] = []
    recipes, rejected, duplicates = dataset.validate_recipes([draft])
    assert not recipes and not duplicates
    assert rejected[0]["id"] == "themealdb:123"
    assert rejected[0]["errors"][0]["loc"] == ("steps",)
    assert "input" not in rejected[0]["errors"][0]


def test_import_format_preserves_provenance_media_and_ingredient_roles() -> None:
    """既有导入器接收 name/record，媒体元数据留在 record 原文中。"""
    recipe = dataset.DatasetRecipe.model_validate(dataset.normalize_themealdb(meal_record()))
    recipe.ingredients[1].role = "aux"
    payload = dataset.import_payload(recipe)
    assert set(payload) == {"name", "record"}
    assert payload["record"]["ingredients"] == [
        {"name": "Pasta", "amount_text": "100 g", "unit": None}
    ]
    assert payload["record"]["aux_ingredients"][0]["name"] == "Salt"
    assert payload["record"]["source_uri"] == recipe.source.url
    assert payload["record"]["images"][0]["license"] == "unknown"
    assert payload["record"]["cuisine"] == ["Italian"]
    assert payload["record"]["source"]["record_id"] == "123"


def test_image_url_refuses_non_web_protocol() -> None:
    """数据契约不会保留可执行协议或带用户凭据的图片 URL。"""
    draft = dataset.normalize_themealdb(meal_record())
    draft["images"][0]["url"] = "javascript:alert(1)"
    with pytest.raises(ValidationError):
        dataset.DatasetRecipe.model_validate(draft)


def test_jsonl_preserves_unicode_line_separator_in_instructions(tmp_path: Path) -> None:
    """国际菜谱原文中的 U+2028 不应被当成 JSONL 记录边界。"""
    entry = meal_record()
    entry["strInstructions"] = "Mix.\u2028Then cook.\u0085Serve."
    recipes, _, _ = dataset.validate_recipes([dataset.normalize_themealdb(entry)])
    path = tmp_path / "recipes.jsonl"
    dataset.write_jsonl(path, (recipe.model_dump() for recipe in recipes))
    assert dataset.read_recipe_jsonl(path) == recipes


def test_images_are_decoded_and_cached_by_content(tmp_path: Path) -> None:
    """只有能解码的真实图片计为 verified，不把 HTTP 成功页当图片。"""
    stream = io.BytesIO()
    Image.new("RGB", (128, 96), color="red").save(stream, format="PNG")

    class Cache:
        """用内存图像替代外部请求，覆盖真实解码流程。"""

        def get(self, url: str, *, max_bytes: int) -> tuple[bytes, dict]:
            return (
                b"<html>not an image</html>" if url.endswith("bad.jpg") else stream.getvalue()
            ), {}

    first = dataset.DatasetRecipe.model_validate(dataset.normalize_themealdb(meal_record("1")))
    second = copy.deepcopy(first)
    second.images[0].url = "https://www.themealdb.com/images/bad.jpg"
    dataset.download_recipe_images([first, second], cast(DownloadCache, Cache()), tmp_path, 1)
    assert first.images[0].validation_status == "verified"
    assert (first.images[0].width, first.images[0].height) == (128, 96)
    assert first.images[0].local_path is not None
    assert (tmp_path / first.images[0].local_path).is_file()
    assert second.images[0].validation_status == "failed"
    assert second.images[0].error


def test_truncated_jpeg_does_not_count_as_verified(tmp_path: Path) -> None:
    """JPEG 头部可读不代表像素完整；必须实际解码整张图片。"""
    stream = io.BytesIO()
    Image.new("RGB", (128, 128), color="red").save(stream, format="JPEG")
    truncated = stream.getvalue()[:-100]

    class Cache:
        """返回具有正常尺寸头但像素正文不完整的 JPEG。"""

        def get(self, url: str, *, max_bytes: int) -> tuple[bytes, dict]:
            return truncated, {}

    recipe = dataset.DatasetRecipe.model_validate(dataset.normalize_themealdb(meal_record()))
    dataset.download_recipe_images([recipe], cast(DownloadCache, Cache()), tmp_path, 1)
    assert recipe.images[0].validation_status == "failed"
    assert not list((tmp_path / "media").iterdir())


def test_offline_build_outputs_are_reproducible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """完整流水线输出可重复，新菜谱导入文件不会重复包含原有库。"""
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {"鸡蛋": {"主食材": [["鸡蛋", "2个"]], "辅料": [], "做法": "1:打散2:炒熟"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        dataset, "collect_sources", lambda *_: ([], [meal_record()], {"receipts": []})
    )
    args = argparse.Namespace(
        output=tmp_path / "output",
        offline=True,
        revision="a" * 40,
        workers=1,
        collect_only=False,
        baseline=baseline,
        download_images=False,
        corrections=None,
        nutrition_profiles=None,
        nutrition_matches=None,
        nutrition_registry=None,
    )
    result = dataset.build_dataset(args)
    first = (args.output / "recipes.jsonl").read_bytes()
    dataset.build_dataset(args)
    assert (args.output / "recipes.jsonl").read_bytes() == first
    assert result["total_recipes"] == 2
    assert result["new_recipes"] == 1
    imported = json.loads((args.output / "expansion.import.json").read_text(encoding="utf-8"))
    assert len(imported) == 1 and imported[0]["record"]["id"] == "themealdb:123"
    manifest = json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["recipes.jsonl"]["sha256"] == dataset.digest_bytes(first)
    assert dataset.verify_dataset(args.output)["recipes"] == 2
    (args.output / "recipes.jsonl").write_bytes(first + b" ")
    with pytest.raises(ValueError, match="integrity"):
        dataset.verify_dataset(args.output)
