"""构建有来源、可离线复现的中外菜谱数据集，不连接业务数据库。

首次运行可加 --download-images 缓存原图；--offline 从已校验缓存重建。
缺少的份数、耗时、菜系和许可保持未知，不使用模型补造食谱事实。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import string
import sys
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.recipe_dataset_corrections import (
    RecipeCuration,
    apply_recipe_corrections,
)
from scripts.recipe_dataset_http import DownloadCache
from scripts.recipe_dataset_nutrition import (
    RecipeNutrition,
    apply_nutrition_registry,
    apply_recipe_nutrition,
)
from scripts.recipe_dataset_sources import parse_howtocook_recipe

HOWTOCOOK_REVISION = "58c1b9af7900a9489c340bca39ef94a9a62314b1"
MEALDB_API = "https://www.themealdb.com/api/json/v1/1"
MEALDB_TERMS = "https://www.themealdb.com/terms_of_use.php"
SCHEMA_VERSION = "1.0.0"
ARTIFACT_NAMES = (
    "recipes.jsonl",
    "recipes.with-images.jsonl",
    "recipes.open-license.jsonl",
    "expansion.import.json",
    "source-snapshot.json",
    "quality-report.json",
    "recipe.schema.json",
    "rejected.jsonl",
    "duplicates.jsonl",
    "README.md",
    "corrections-report.json",
    "nutrition-report.json",
)


class DatasetModel(BaseModel):
    """拒绝未知字段和隐式类型转换，及时暴露上游格式变化。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class Ingredient(DatasetModel):
    """食材名称与来源原样记录的用量；不把一勺估算成克。"""

    name: str = Field(min_length=1)
    amount: str | None = None
    unit: str | None = None
    role: Literal["main", "aux", "unspecified"] = "unspecified"


class RecipeSource(DatasetModel):
    """单条记录的出处、版本与发布者声明的使用条件。"""

    provider: Literal["openkg", "howtocook", "themealdb"]
    record_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    original_url: str | None = None
    license: str
    license_url: str
    license_status: Literal["review_required", "repository_declared", "development_only"]
    attribution: str
    revision: str


class RecipeImage(DatasetModel):
    """图片出处与验证结果独立于菜谱文字许可，索引从一开始。"""

    url: str
    role: Literal["hero", "step", "unspecified"]
    step_index: int | None = Field(default=None, ge=1)
    alt: str = ""
    license: str
    license_status: Literal["repository_declared", "review_required", "provider_confirmed"]
    source_url: str
    author: str | None = None
    validation_status: Literal["not_downloaded", "verified", "failed", "blocked"] = "not_downloaded"
    local_path: str | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """只接受正常 HTTP 图片链接；下载域名另由缓存客户端约束。"""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("Image URL must be an HTTP(S) URL without credentials")
        return value


class Durations(DatasetModel):
    """保留上游时间表达；没有记录时使用 null。"""

    prep: str | None = None
    cook: str | None = None
    total: str | None = None


class DatasetRecipe(DatasetModel):
    """统一的菜谱文件契约；来源稳定身份与内容指纹分别记录。"""

    id: str
    name: str = Field(min_length=1)
    language: str
    country: str | None = None
    video_url: str | None = None
    description: str = ""
    ingredients: list[Ingredient] = Field(min_length=1)
    ingredients_raw: list[str] = Field(default_factory=list)
    steps: list[str] = Field(min_length=1)
    instructions_raw: str | None = None
    tips: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    cuisines: list[str] = Field(default_factory=list)
    images: list[RecipeImage] = Field(default_factory=list)
    source: RecipeSource
    additional_sources: list[RecipeSource] = Field(default_factory=list)
    durations: Durations = Field(default_factory=Durations)
    servings: str | None = None
    tags: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    content_sha256: str = ""
    curation: RecipeCuration | None = None
    nutrition: RecipeNutrition | None = None

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, steps: list[str]) -> list[str]:
        """空步骤应被拒绝，不能以空数组掩盖解析失败。"""
        if any(not step.strip() for step in steps):
            raise ValueError("Recipe steps must not be blank")
        return steps


def stable_json(value: Any) -> str:
    """统一序列化以计算指纹，保持 Unicode 可读且拒绝非有限数。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def recipe_dump(recipe: DatasetRecipe) -> dict:
    """只给已修订的菜谱添加修订元数据，其他行维持原格式。"""
    record = recipe.model_dump()
    if recipe.curation is None:
        record.pop("curation")
    if recipe.nutrition is None:
        record.pop("nutrition")
    return record


def digest_bytes(value: bytes) -> str:
    """返回输入快照或图片的 SHA-256。"""
    return hashlib.sha256(value).hexdigest()


def text_or_none(value: Any) -> str | None:
    """清洗上游可选文本；保留明确记录的数值零。"""
    if value is None:
        return None
    if type(value) not in (str, int, float):
        raise ValueError("Expected recorded text or a number")
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text if text else None


def labels(value: Any) -> list[str]:
    """兼容源数据的单值和多值分类，不从菜名猜测菜系。"""
    if value is None:
        return []
    if isinstance(value, list):
        return list(dict.fromkeys(label for item in value for label in labels(item)))
    text = text_or_none(value)
    return (
        []
        if text is None
        else [part.strip() for part in re.split(r"[、/,，；;]", text) if part.strip()]
    )


def split_recorded_steps(text: str) -> list[str]:
    """按同种分隔符的连续编号拆步，保留明确的配比和时刻表达。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    first = re.match(r"1[:：]", normalized)
    if first is not None:
        boundaries = [first]
        separator = re.escape(normalized[first.end() - 1])
        rest = normalized[first.end() :]
        for match in re.finditer(rf"(?<!\d)(\d{{1,3}}){separator}", rest):
            before = rest[max(0, match.start() - 12) : match.start()]
            after = rest[match.end() :]
            if re.match(r"\d", after) and (
                re.search(r"(?:比|比例|配比|或者|比为|比是|上午|下午|晚上|凌晨|时刻)\s*$", before)
                or re.match(r"\d+(?:\.\d+)?\s*(?:[，,；;。%％）)]|$)", after)
            ):
                continue
            if int(match[1]) == len(boundaries) + 1:
                # 后续匹配基于子串，转换回原文的位置后再切片。
                boundaries.append(match)
        starts = [0] + [first.end() + match.start() for match in boundaries[1:]]
        ends = [first.end()] + [first.end() + match.end() for match in boundaries[1:]]
        steps = []
        for index, start in enumerate(ends):
            end = starts[index + 1] if index + 1 < len(starts) else len(normalized)
            if step := normalized[start:end].strip():
                steps.append(step)
        return steps
    # 段落中的句子保持在一起，温度、计量和动作顺序不会被句号拆散。
    return [line.strip() for line in normalized.split("\n") if line.strip()]


def normalize_openkg(name: str, entry: dict, revision: str) -> dict:
    """规范化旧库；246 条只有辅料的记录同样保留其真实原料。"""
    ingredients = []
    flags = []
    for field, role in (("主食材", "main"), ("辅料", "aux")):
        for item in entry.get(field, []):
            if not isinstance(item, list) or not item:
                raise ValueError(f"Invalid OpenKG ingredient: {item!r}")
            ingredient_name = text_or_none(item[0])
            if ingredient_name is None:
                flags.append("empty_ingredient_row_removed")
                continue
            ingredients.append(
                {
                    "name": ingredient_name,
                    "amount": text_or_none(item[1]) if len(item) > 1 else None,
                    "unit": None,
                    "role": role,
                }
            )
    instructions = text_or_none(entry.get("做法"))
    steps = [] if instructions is None else split_recorded_steps(instructions)
    if instructions is not None and len(steps) < 3:
        flags.append("step_numbering_needs_review")
    return {
        "id": "openkg:" + digest_bytes(name.encode("utf-8"))[:20],
        "name": name.strip(),
        "language": "zh-CN",
        "ingredients": ingredients,
        "steps": steps,
        "instructions_raw": instructions,
        "quality_flags": sorted(set(flags)),
        "categories": labels(entry.get("类型")),
        "cuisines": labels(entry.get("菜系")),
        "durations": {"total": text_or_none(entry.get("耗时"))},
        "tags": [
            f"{key}：{entry[key]}"
            for key in ("口味", "工艺")
            if text_or_none(entry.get(key)) is not None
        ],
        "source": {
            "provider": "openkg",
            "record_id": name,
            "url": "http://openkg.cn/dataset/recipegraph",
            "original_url": None,
            "license": "unknown",
            "license_url": "http://openkg.cn/dataset/recipegraph",
            "license_status": "review_required",
            "attribution": "OpenKG RecipeGraph",
            "revision": "sha256:" + revision,
        },
    }


def normalize_themealdb(entry: dict) -> dict:
    """映射官方接口原始字段；CC 确认标志不等于具体 CC 许可证。"""
    recipe_id = entry["idMeal"]
    name = entry["strMeal"]
    recipe_url = "https://www.themealdb.com/meal/" + quote(recipe_id, safe="")
    ingredients = []
    for index in range(1, 21):
        ingredient_name = text_or_none(entry.get(f"strIngredient{index}"))
        if ingredient_name is not None:
            ingredients.append(
                {
                    "name": ingredient_name,
                    "amount": text_or_none(entry.get(f"strMeasure{index}")),
                    "unit": None,
                }
            )
    image_url = text_or_none(entry.get("strMealThumb"))
    confirmed = str(entry.get("strCreativeCommonsConfirmed", "")).lower() in {"yes", "true", "1"}
    instructions = text_or_none(entry.get("strInstructions"))
    return {
        "id": "themealdb:" + recipe_id,
        "name": name,
        "language": "en",
        "country": text_or_none(entry.get("strCountry")),
        "video_url": text_or_none(entry.get("strYoutube")),
        "ingredients": ingredients,
        "steps": [] if instructions is None else split_recorded_steps(instructions),
        "instructions_raw": instructions,
        "categories": labels(entry.get("strCategory")),
        "cuisines": labels(entry.get("strArea")),
        "tags": labels(entry.get("strTags")),
        "images": (
            []
            if image_url is None
            else [
                {
                    "url": image_url,
                    "role": "hero",
                    "alt": name,
                    "source_url": text_or_none(entry.get("strImageSource")) or recipe_url,
                    "license": "CC-confirmed-unspecified" if confirmed else "unknown",
                    "license_status": "provider_confirmed" if confirmed else "review_required",
                }
            ]
        ),
        "source": {
            "provider": "themealdb",
            "record_id": recipe_id,
            "url": recipe_url,
            "original_url": text_or_none(entry.get("strSource")),
            "license": "TheMealDB API terms (development snapshot)",
            "license_url": MEALDB_TERMS,
            "license_status": "development_only",
            "attribution": "TheMealDB / original recipe contributors",
            "revision": "sha256:" + digest_bytes(stable_json(entry).encode("utf-8")),
        },
    }


def collect_sources(
    cache: DownloadCache, revision: str, workers: int
) -> tuple[list[tuple[str, str]], list[dict], dict]:
    """固定 Git 提交并获取 A–Z 官方接口快照；任一正文下载失败即终止。"""
    tree_url = f"https://api.github.com/repos/Anduin2017/HowToCook/git/trees/{revision}?recursive=1"
    tree_body, tree_receipt = cache.get(tree_url)
    tree = json.loads(tree_body)
    if tree.get("truncated"):
        raise ValueError("HowToCook tree is truncated; refusing an incomplete source snapshot")
    paths = sorted(
        item["path"]
        for item in tree["tree"]
        if item["type"] == "blob"
        and item["path"].startswith("dishes/")
        and item["path"].endswith(".md")
    )
    if not paths:
        raise ValueError("HowToCook snapshot contains no recipe documents")
    urls = [
        (
            path,
            f"https://raw.githubusercontent.com/Anduin2017/HowToCook/{revision}/{quote(path, safe='/')}",
        )
        for path in paths
    ]
    urls += [
        ("mealdb:" + letter, f"{MEALDB_API}/search.php?f={letter}")
        for letter in string.ascii_lowercase
    ]
    urls += [
        (
            "howtocook:license",
            f"https://raw.githubusercontent.com/Anduin2017/HowToCook/{revision}/LICENSE",
        ),
        ("themealdb:terms", MEALDB_TERMS),
    ]
    documents: dict[str, str] = {}
    receipts = [tree_receipt]
    meals: dict[str, dict] = {}
    saturated_letters = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {executor.submit(cache.get, url): key for key, url in urls}
        for count, future in enumerate(as_completed(pending), start=1):
            key = pending[future]
            body, receipt = future.result()
            receipts.append(receipt)
            if key.startswith("mealdb:"):
                payload = json.loads(body)
                if "meals" not in payload or (
                    payload["meals"] is not None and not isinstance(payload["meals"], list)
                ):
                    raise ValueError(f"Unexpected TheMealDB response for {key}")
                entries = [] if payload["meals"] is None else payload["meals"]
                if len(entries) >= 100:
                    saturated_letters.append(key[-1])
                for entry in entries:
                    existing = meals.get(entry["idMeal"])
                    if existing is not None and existing != entry:
                        raise ValueError(f"Conflicting meal snapshot: {entry['idMeal']}")
                    meals[entry["idMeal"]] = entry
            elif key.startswith("dishes/"):
                documents[key] = body.decode("utf-8-sig")
            if count % 40 == 0 or count == len(urls):
                print(f"Source snapshots: {count}/{len(urls)}", flush=True)
    if not documents or not meals:
        raise ValueError("A required recipe provider returned an empty snapshot")
    return (
        sorted(documents.items()),
        [meals[key] for key in sorted(meals)],
        {
            "howtocook_revision": revision,
            "howtocook_documents": len(documents),
            "themealdb_records": len(meals),
            "themealdb_queries": 26,
            "themealdb_saturated_letters": sorted(saturated_letters),
            "themealdb_coverage": "A-Z first-letter endpoints; not a guaranteed full database export",
            "receipts": sorted(receipts, key=lambda item: item["url"]),
        },
    )


def content_fingerprint(recipe: DatasetRecipe) -> str:
    """仅按原料、原始用量和有序步骤识别完全重复，不按标题合并。"""

    def normalized(value: str | None) -> str:
        return (
            ""
            if value is None
            else re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()
        )

    content = {
        "ingredients": sorted(
            (normalized(item.name), normalized(item.amount), normalized(item.unit))
            for item in recipe.ingredients
        ),
        "steps": [normalized(step) for step in recipe.steps],
    }
    return digest_bytes(stable_json(content).encode("utf-8"))


def validate_recipes(drafts: list[dict]) -> tuple[list[DatasetRecipe], list[dict], list[dict]]:
    """校验并去掉完全重复项；拒绝项和合并原因逐条留档。"""
    recipes: list[DatasetRecipe] = []
    rejected = []
    duplicates = []
    by_content: dict[str, DatasetRecipe] = {}
    ids = set()
    for draft in drafts:
        try:
            recipe = DatasetRecipe.model_validate(draft)
        except ValidationError as error:
            rejected.append(
                {
                    "id": draft.get("id"),
                    "name": draft.get("name"),
                    "errors": error.errors(
                        include_url=False, include_context=False, include_input=False
                    ),
                }
            )
            continue
        if recipe.id in ids:
            raise ValueError(f"Duplicate source identity: {recipe.id}")
        ids.add(recipe.id)
        recipe.content_sha256 = content_fingerprint(recipe)
        if recipe.content_sha256 in by_content:
            kept = by_content[recipe.content_sha256]
            kept.additional_sources.append(recipe.source)
            known_images = {image.url for image in kept.images}
            kept.images.extend(image for image in recipe.images if image.url not in known_images)
            duplicates.append(
                {
                    "kept_id": kept.id,
                    "removed_id": recipe.id,
                    "name": recipe.name,
                    "reason": "identical_ingredients_and_ordered_steps",
                }
            )
            continue
        by_content[recipe.content_sha256] = recipe
        recipes.append(recipe)
    return sorted(recipes, key=lambda recipe: recipe.id), rejected, duplicates


def download_recipe_images(
    recipes: list[DatasetRecipe], cache: DownloadCache, output: Path, workers: int
) -> None:
    """下载并实际解码图片；失败留档，只有成功项进入本地有图子集。"""
    urls = sorted({image.url for recipe in recipes for image in recipe.images})
    media = output / "media"
    media.mkdir(exist_ok=True)

    def download(url: str) -> dict:
        """只接受已知图片宿主，网络错误和图片解码失败逐项报告。"""
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "raw.githubusercontent.com",
            "www.themealdb.com",
            "themealdb.com",
        }:
            return {
                "validation_status": "blocked",
                "error": "Image host is outside supported source domains",
            }
        try:
            body, _receipt = cache.get(url, max_bytes=12 * 1024 * 1024)
            with Image.open(io.BytesIO(body)) as image:
                image.verify()
            with Image.open(io.BytesIO(body)) as image:
                width, height = image.size
                image_format = image.format
                if width * height > 40_000_000:
                    raise ValueError("Image exceeds the 40 megapixel decoding limit")
                image.load()
            if width < 64 or height < 64:
                raise ValueError("Image is smaller than 64px")
            # 部分手机 JPEG 带 MPF 信息，Pillow 称为 MPO；验证其默认首帧并保留原文件。
            extensions = {
                "JPEG": ".jpg",
                "MPO": ".jpg",
                "PNG": ".png",
                "WEBP": ".webp",
                "GIF": ".gif",
            }
            if image_format not in extensions:
                raise ValueError(f"Unsupported image format: {image_format}")
            digest = digest_bytes(body)
            path = media / (digest + extensions[image_format])
            if not path.exists() or digest_bytes(path.read_bytes()) != digest:
                path.write_bytes(body)
            return {
                "validation_status": "verified",
                "local_path": path.relative_to(output).as_posix(),
                "sha256": digest,
                "width": width,
                "height": height,
            }
        except (
            OSError,
            ValueError,
            SyntaxError,
            httpx.HTTPError,
            Image.DecompressionBombError,
        ) as error:
            return {"validation_status": "failed", "error": f"{type(error).__name__}: {error}"}

    downloaded = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {executor.submit(download, url): url for url in urls}
        for count, future in enumerate(as_completed(pending), start=1):
            downloaded[pending[future]] = future.result()
            if count % 40 == 0 or count == len(urls):
                print(f"Image validation: {count}/{len(urls)}", flush=True)
    for recipe in recipes:
        recipe.images = [image.model_copy(update=downloaded[image.url]) for image in recipe.images]


def recipe_flags(recipe: DatasetRecipe) -> list[str]:
    """报告缺失而不凭任意总分声称食谱已经过烹饪验证。"""
    flags = []
    if not recipe.cuisines:
        flags.append("cuisine_not_recorded")
    if not any((recipe.durations.prep, recipe.durations.cook, recipe.durations.total)):
        flags.append("duration_not_recorded")
    if recipe.servings is None:
        flags.append("servings_not_recorded")
    if any(ingredient.amount is None for ingredient in recipe.ingredients):
        flags.append("ingredient_amount_missing")
    if not recipe.images:
        flags.append("image_not_recorded")
    elif not any(image.validation_status == "verified" for image in recipe.images):
        flags.append("no_verified_local_image")
    if recipe.source.license_status != "repository_declared":
        flags.append("source_usage_restricted_or_unreviewed")
    if any(image.license_status == "review_required" for image in recipe.images):
        flags.append("image_license_review_required")
    if (
        recipe.curation is not None
        and recipe.curation.supplemental_content_license_status == "review_required"
    ):
        flags.append("supplemental_source_usage_review_required")
    return flags


def is_open_license_recipe(recipe: DatasetRecipe) -> bool:
    """开放子集同时考虑原文、图片和本轮引入的作者补充内容。"""
    return (
        recipe.source.license_status == "repository_declared"
        and all(image.license_status == "repository_declared" for image in recipe.images)
        and (
            recipe.curation is None
            or recipe.curation.supplemental_content_license_status != "review_required"
        )
    )


def import_payload(recipe: DatasetRecipe) -> dict:
    """转换成现有 /knowledge/recipes/batch 契约，保留图片和完整出处。"""
    record = recipe_dump(recipe)
    record.pop("name")
    record["source_uri"] = recipe.source.url
    record["cuisine"] = record.pop("cuisines")
    record["category"] = record.pop("categories")
    record["ingredients"] = [
        {"name": ingredient.name, "amount_text": ingredient.amount, "unit": ingredient.unit}
        for ingredient in recipe.ingredients
        if ingredient.role != "aux"
    ]
    record["aux_ingredients"] = [
        {"name": ingredient.name, "amount_text": ingredient.amount, "unit": ingredient.unit}
        for ingredient in recipe.ingredients
        if ingredient.role == "aux"
    ]
    for key, value in (
        ("prep_time", recipe.durations.prep),
        ("cooking_time", recipe.durations.cook),
        ("total_time", recipe.durations.total),
    ):
        if value is not None:
            record[key] = value
    return {"name": recipe.name, "record": record}


def write_jsonl(path: Path, rows: Any) -> None:
    """逐条写出 UTF-8 JSONL，避免数组和额外缩进放大数据体积。"""
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(stable_json(row) + "\n")


def read_recipe_jsonl(path: Path) -> list[DatasetRecipe]:
    """按真实换行读取 JSONL，保留正文中的 Unicode 行分隔字符。"""
    with path.open(encoding="utf-8") as stream:
        return [DatasetRecipe.model_validate_json(line) for line in stream]


def write_json(path: Path, value: Any) -> None:
    """写出可读元数据与导入文件。"""
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def dataset_report(
    recipes: list[DatasetRecipe], rejected: list[dict], duplicates: list[dict]
) -> dict:
    """全量计算来源、图像、完整度和菜系覆盖，避免用抽样估算。"""
    providers = Counter(recipe.source.provider for recipe in recipes)
    cuisines = Counter(cuisine for recipe in recipes for cuisine in recipe.cuisines)
    by_source = {}
    for provider in sorted(providers):
        selected = [recipe for recipe in recipes if recipe.source.provider == provider]
        by_source[provider] = {
            "recipes": len(selected),
            "with_image_url": sum(bool(recipe.images) for recipe in selected),
            "with_verified_local_image": sum(
                any(image.validation_status == "verified" for image in recipe.images)
                for recipe in selected
            ),
            "with_recorded_cuisine": sum(bool(recipe.cuisines) for recipe in selected),
            "with_recorded_country": sum(recipe.country is not None for recipe in selected),
            "with_recorded_duration": sum(
                any((recipe.durations.prep, recipe.durations.cook, recipe.durations.total))
                for recipe in selected
            ),
            "with_all_ingredient_amounts": sum(
                all(item.amount is not None for item in recipe.ingredients) for recipe in selected
            ),
        }
    name_groups = defaultdict(list)
    for recipe in recipes:
        name = re.sub(r"^(?:(?:#[^#]+#|【[^】]+】|\[[^\]]+\])\s*)+", "", recipe.name)
        key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).casefold()
        name_groups[key].append(recipe.id)
    return {
        "schema_version": SCHEMA_VERSION,
        "total_recipes": len(recipes),
        "curated_recipes": sum(recipe.curation is not None for recipe in recipes),
        "nutrition_enriched_recipes": sum(recipe.nutrition is not None for recipe in recipes),
        "new_recipes": sum(recipe.source.provider != "openkg" for recipe in recipes),
        "ingredients": sum(len(recipe.ingredients) for recipe in recipes),
        "steps": sum(len(recipe.steps) for recipe in recipes),
        "image_references": sum(len(recipe.images) for recipe in recipes),
        "unique_image_urls": len({image.url for recipe in recipes for image in recipe.images}),
        "image_validation": dict(
            Counter(image.validation_status for recipe in recipes for image in recipe.images)
        ),
        "image_license_status": dict(
            Counter(image.license_status for recipe in recipes for image in recipe.images)
        ),
        "with_verified_local_image": sum(
            any(image.validation_status == "verified" for image in recipe.images)
            for recipe in recipes
        ),
        "with_hero_image_url": sum(
            any(image.role == "hero" for image in recipe.images) for recipe in recipes
        ),
        "source_license_status": dict(Counter(recipe.source.license_status for recipe in recipes)),
        "quality_flags": dict(Counter(flag for recipe in recipes for flag in recipe.quality_flags)),
        "languages": dict(Counter(recipe.language for recipe in recipes)),
        "by_source": by_source,
        "cuisines": dict(cuisines.most_common()),
        "countries": dict(
            Counter(
                recipe.country for recipe in recipes if recipe.country is not None
            ).most_common()
        ),
        "rejected_count": len(rejected),
        "exact_duplicates_removed": len(duplicates),
        "same_name_variant_groups": sum(len(ids) > 1 for ids in name_groups.values()),
        "same_name_variants_preserved": [ids for ids in name_groups.values() if len(ids) > 1],
        "limitations": [
            "未经过逐菜实际烹饪验证；完整度只表示字段存在。",
            "原有 OpenKG 记录和 TheMealDB 开发快照不能视为已获无限制商业再分发授权。",
            "TheMealDB A-Z 接口快照不保证等于供应商完整数据库；原文为英文，不冒称人工中文翻译。",
            "缺失字段优先查证补齐；营养补充按官方原料数据和明确用量计算，原料小计不冒充成菜热量。",
            "HowToCook 图片按来源位置标注；不明确的图片不冒充成品图。",
        ],
    }


def write_readme(output: Path, report: dict, revision: str) -> None:
    """随数据生成实际统计、使用边界和可复现命令。"""
    rows = [
        f"| {provider} | {values['recipes']:,} | {values['with_image_url']:,} | {values['with_verified_local_image']:,} |"
        for provider, values in report["by_source"].items()
    ]
    text = f"""# GustoBot Recipes v1

本地开发用的中外菜谱快照，共 **{report['total_recipes']:,}** 条，新增
**{report['new_recipes']:,}** 条；**{report['with_verified_local_image']:,}** 条拥有已下载并解码验证的图片。
字段存在不等于经过实际烹饪测试。国际食谱保留英文原文，不宣称为人工中文译本。

| 来源 | 菜谱 | 含图片链接 | 含已验证本地图片 |
| --- | ---: | ---: | ---: |
{chr(10).join(rows)}

## 文件

- `recipes.jsonl`：统一字段的完整开发快照，每行一条；保留原有菜谱的既有菜系。
- `recipes.with-images.jsonl`：至少一张本地图片通过解码和摘要验证的菜谱。
- `recipes.open-license.jsonl`：上游仓库声明开放许可、且所有引用图片同样有仓库许可声明的子集。
- `expansion.import.json`：仅新增菜谱，格式为现有服务接受的 `name` / `record` 数组。
- `recipe.schema.json`：数据契约；`quality-report.json`：全量完整度与菜系/国家覆盖。
- `source-snapshot.json`：正文请求 URL、抓取时间、SHA-256 与固定 Git 提交。
- `manifest.json`：本轮输入快照与产物摘要；`rejected.jsonl` / `duplicates.jsonl`：拒绝项和完全重复项。
- `verification.json`：最近一次全量离线校验回执，绑定对应 manifest 的摘要。
- `corrections-report.json`：已应用的逐菜修订批次、原问题覆盖数和证据文件摘要。
- `nutrition-report.json`：官方原料营养补全范围、可计算项数及成分表/匹配配置摘要。
- `media/`：按内容 SHA-256 命名的实际图片；`.cache/`：原始 HTTP 正文与校验回执。

图片与缓存保存在本机，未纳入 Git；在另一台机器上运行下面命令可重新获取。
`local_path` 相对于本目录。`hero` 是源数据明确标记的成品图；`step` 是步骤图，
`unspecified` 不保证是成品图。未知份数、时长、热量和过敏原均保持未知。
`amount` 保留来源原始单位、范围和公式，未擅自折算；HowToCook 的 `ingredients_raw`
保留原料列表原文，份数相关计算说明在 `tips` 中。图片来源和许可与文字出处分别记录。

## 重建与校验

在仓库根目录执行（使用项目现有 Python 依赖，无新增依赖）：

```powershell
python scripts/build_recipe_dataset.py --download-images
python scripts/build_recipe_dataset.py --offline --download-images
python scripts/build_recipe_dataset.py --verify
```

本次锁定 HowToCook 提交 `{revision}`；更新时显式传 `--revision <40位SHA>`。
已有缓存不会静默刷新；TheMealDB 更新应选择新的 `--output` 目录形成独立快照。
`--offline --download-images` 需要本轮成功图片缓存；失败与域名未支持的链接会保留状态。

## 使用条件

完整合并集没有统一的无限制商用许可证。
OpenKG 的上游数据许可仍需核对。HowToCook 采用仓库声明的 Unlicense，逐条保留提交与署名；
外部图片不会自动继承该许可。TheMealDB 通过官方测试接口获取，用作本地开发，
公开发布时应按[官方条款](https://www.themealdb.com/terms_of_use.php)使用生产授权并核对第三方内容。
`CC-confirmed-unspecified` 仅表示供应商确认过 CC 标志，没有据此编造许可证版本。
`recipes.open-license.jsonl` 只反映上游声明，不代表额外的独立权利核验。
TheMealDB A–Z 查询存在每次结果上限，覆盖情况和触及上限的字母记录在来源快照中。

当前业务服务可保留 `record` 中的图片与许可原文，但图片尚未映射为前端响应字段。
此构建器只写离线文件，未自动写入 MySQL、Neo4j 或 Milvus。

已修订菜谱共 {report['curated_recipes']:,} 条，`curation` 保留每项改动对应的一手/官方资料与原记录摘要。
后续按固定 ID 分批执行查证、补全、修复和复核；修订在重建时自动应用。文献复核不等于实际下厨试验。

当前 **{report['nutrition_enriched_recipes']}** 条包含 `nutrition`：逐项提供官方食物状态、每100g营养、来源、
用量换算和已知原料小计。`listed_input_total` 也只是全部所列原料的投料总量；
`known_input_subtotal` 有未计入项，均不能直接当每份、每100g成菜或实际摄入热量。
新增作者变体的补充内容许可单独待核，不沿用原HowToCook许可进入开放子集。
"""
    (output / "README.md").write_text(text, encoding="utf-8")


def verify_dataset(output: Path) -> dict:
    """全量检查文件摘要、唯一身份、原图与导入导出闭环，不访问网络。"""
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    root = output.resolve()
    for name, artifact in manifest["artifacts"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Manifest artifact path escapes the dataset directory")
        if (
            path.stat().st_size != artifact["bytes"]
            or digest_bytes(path.read_bytes()) != artifact["sha256"]
        ):
            raise ValueError(f"Artifact integrity check failed: {name}")
    recipes = read_recipe_jsonl(root / "recipes.jsonl")
    ids = [recipe.id for recipe in recipes]
    if len(ids) != len(set(ids)):
        raise ValueError("Dataset contains duplicate source identities")
    checked_images = set()
    for recipe in recipes:
        if recipe.content_sha256 != content_fingerprint(recipe):
            raise ValueError(f"Recipe content fingerprint mismatch: {recipe.id}")
        for image in recipe.images:
            if image.step_index is not None and image.step_index > len(recipe.steps):
                raise ValueError(f"Image points beyond the recipe steps: {recipe.id}")
            if image.validation_status != "verified":
                continue
            if image.local_path is None or image.sha256 is None:
                raise ValueError(f"Verified image has no file receipt: {recipe.id}")
            path = (root / image.local_path).resolve()
            if not path.is_relative_to(root / "media"):
                raise ValueError("Image path escapes the dataset media directory")
            if path in checked_images:
                continue
            body = path.read_bytes()
            if digest_bytes(body) != image.sha256:
                raise ValueError(f"Local image integrity check failed: {image.local_path}")
            with Image.open(io.BytesIO(body)) as decoded:
                decoded.verify()
            with Image.open(io.BytesIO(body)) as decoded:
                if decoded.size != (image.width, image.height):
                    raise ValueError(f"Image dimension mismatch: {image.local_path}")
                decoded.load()
            checked_images.add(path)
    expected_imports = [
        import_payload(recipe) for recipe in recipes if recipe.source.provider != "openkg"
    ]
    actual_imports = json.loads((root / "expansion.import.json").read_text(encoding="utf-8"))
    if actual_imports != expected_imports:
        raise ValueError("Expansion import does not match the canonical dataset")
    for filename, expected in (
        (
            "recipes.with-images.jsonl",
            [
                recipe
                for recipe in recipes
                if any(image.validation_status == "verified" for image in recipe.images)
            ],
        ),
        (
            "recipes.open-license.jsonl",
            [recipe for recipe in recipes if is_open_license_recipe(recipe)],
        ),
    ):
        actual = read_recipe_jsonl(root / filename)
        if actual != expected:
            raise ValueError(f"Subset does not match the canonical dataset: {filename}")
    report = json.loads((root / "quality-report.json").read_text(encoding="utf-8"))
    if report["total_recipes"] != len(recipes) or report["new_recipes"] != len(expected_imports):
        raise ValueError("Quality report counts do not match the dataset")
    for filename in ("corrections-report.json", "nutrition-report.json"):
        support = json.loads((root / filename).read_text(encoding="utf-8"))
        for source in support["source_files"]:
            if digest_bytes(Path(source["path"]).read_bytes()) != source["sha256"]:
                raise ValueError(f"Supporting evidence checksum mismatch: {source['path']}")
    nutrition_report = json.loads((root / "nutrition-report.json").read_text(encoding="utf-8"))
    if nutrition_report["enriched_recipes"]:
        if "registry_path" in nutrition_report:
            recalculated, recalculated_report = apply_nutrition_registry(
                [recipe_dump(recipe) for recipe in recipes], Path(nutrition_report["registry_path"])
            )
        else:
            profile_path, matches_path = (
                Path(source["path"]) for source in nutrition_report["source_files"]
            )
            recalculated, recalculated_report = apply_recipe_nutrition(
                [recipe_dump(recipe) for recipe in recipes], profile_path, matches_path
            )
        if (
            recalculated != [recipe_dump(recipe) for recipe in recipes]
            or recalculated_report != nutrition_report
        ):
            raise ValueError("Nutrition calculations are not reproducible from recorded evidence")
    return {
        "status": "verified",
        "recipes": len(recipes),
        "expansion_imports": len(expected_imports),
        "local_image_files": len(checked_images),
        "artifacts": len(manifest["artifacts"]),
    }


def build_dataset(args: argparse.Namespace) -> dict:
    """顺序执行获取、规范化、去重、图片验证和产物登记。"""
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with DownloadCache(output / ".cache", offline=args.offline) as cache:
        documents, meals, snapshot = collect_sources(cache, args.revision, args.workers)
        write_json(output / "source-snapshot.json", snapshot)
        if args.collect_only:
            return {
                "source_snapshots": len(snapshot["receipts"]),
                "howtocook_documents": len(documents),
                "themealdb_records": len(meals),
            }
        baseline_bytes = args.baseline.read_bytes()
        baseline = json.loads(baseline_bytes)
        if not isinstance(baseline, dict) or not baseline:
            raise ValueError("Baseline must be the nonempty OpenKG recipe dictionary")
        baseline_sha = digest_bytes(baseline_bytes)
        drafts = [normalize_openkg(name, entry, baseline_sha) for name, entry in baseline.items()]
        skipped_documents = []
        for path, text in documents:
            parsed = parse_howtocook_recipe(text, path, args.revision)
            if parsed is None:
                skipped_documents.append(path)
            else:
                drafts.append(parsed)
        drafts.extend(normalize_themealdb(entry) for entry in meals)
        recipes, rejected, duplicates = validate_recipes(drafts)
        if args.download_images:
            download_recipe_images(recipes, cache, output, args.workers)
    for recipe in recipes:
        recipe.quality_flags = sorted(set(recipe.quality_flags + recipe_flags(recipe)))
    corrected_records, corrections_report = apply_recipe_corrections(
        [recipe_dump(recipe) for recipe in recipes], args.corrections
    )
    if args.nutrition_profiles is not None or args.nutrition_matches is not None:
        if args.nutrition_profiles is None or args.nutrition_matches is None:
            raise ValueError("Custom nutrition profiles and matches must be specified together")
        corrected_records, nutrition_report = apply_recipe_nutrition(
            corrected_records, args.nutrition_profiles, args.nutrition_matches
        )
    elif args.nutrition_registry is not None:
        corrected_records, nutrition_report = apply_nutrition_registry(
            corrected_records, args.nutrition_registry
        )
    else:
        corrected_records, nutrition_report = apply_recipe_nutrition(corrected_records, None, None)
    recipes = [DatasetRecipe.model_validate(record) for record in corrected_records]
    for recipe in recipes:
        if recipe.curation is not None:
            recipe.content_sha256 = content_fingerprint(recipe)
            recipe.quality_flags = sorted(set(recipe_flags(recipe)))
    report = dataset_report(recipes, rejected, duplicates)
    report["input_records"] = len(drafts)
    report["howtocook_skipped_documents"] = skipped_documents
    write_jsonl(output / "recipes.jsonl", (recipe_dump(recipe) for recipe in recipes))
    write_jsonl(
        output / "recipes.with-images.jsonl",
        (
            recipe_dump(recipe)
            for recipe in recipes
            if any(image.validation_status == "verified" for image in recipe.images)
        ),
    )
    write_jsonl(
        output / "recipes.open-license.jsonl",
        (recipe_dump(recipe) for recipe in recipes if is_open_license_recipe(recipe)),
    )
    write_json(
        output / "expansion.import.json",
        [import_payload(recipe) for recipe in recipes if recipe.source.provider != "openkg"],
    )
    write_jsonl(output / "rejected.jsonl", rejected)
    write_jsonl(output / "duplicates.jsonl", duplicates)
    write_json(output / "quality-report.json", report)
    write_json(output / "corrections-report.json", corrections_report)
    write_json(output / "nutrition-report.json", nutrition_report)
    write_json(output / "recipe.schema.json", DatasetRecipe.model_json_schema())
    write_readme(output, report, args.revision)
    artifacts = {
        name: {
            "sha256": digest_bytes((output / name).read_bytes()),
            "bytes": (output / name).stat().st_size,
        }
        for name in ARTIFACT_NAMES
    }
    write_json(
        output / "manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "baseline": {
                "path": args.baseline.resolve().as_posix(),
                "sha256": baseline_sha,
                "records": len(baseline),
            },
            "howtocook_revision": args.revision,
            "source_snapshots": len(snapshot["receipts"]),
            "downloaded_images": args.download_images,
            "artifacts": artifacts,
            "record_identity_note": "采集时间不进入菜谱记录；原始来源身份和内容SHA-256分开保存。",
            "usage_note": "完整合并集用于本地开发；各原文与图片按逐条许可条件使用。open-license子集仅表示上游仓库声明。",
        },
    )
    (output / "verification.json").unlink(missing_ok=True)
    return {
        key: report[key]
        for key in (
            "total_recipes",
            "new_recipes",
            "with_verified_local_image",
            "rejected_count",
            "exact_duplicates_removed",
            "by_source",
        )
    }


def main(argv: list[str] | None = None) -> int:
    """命令行入口；采集失败返回错误，不生成伪成功统计。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=PROJECT_ROOT / "data/recipe.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/recipes")
    parser.add_argument("--revision", default=HOWTOCOOK_REVISION, help="固定 HowToCook Git SHA")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--download-images", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--verify", action="store_true", help="离线全量验证现有产物")
    parser.add_argument(
        "--corrections", type=Path, default=PROJECT_ROOT / "data/recipes/corrections/registry.json"
    )
    parser.add_argument(
        "--nutrition-profiles",
        type=Path,
        help="与 --nutrition-matches 一起显式覆盖全部已修订批次的营养资料",
    )
    parser.add_argument(
        "--nutrition-matches",
        type=Path,
        help="自定义匹配表；默认按 --nutrition-registry 分批取版本",
    )
    parser.add_argument(
        "--nutrition-registry",
        type=Path,
        default=PROJECT_ROOT / "data/recipes/nutrition/registry.json",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be between 1 and 8")
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be a pinned 40-character Git SHA")
    if args.verify:
        receipt = verify_dataset(args.output)
        receipt["manifest_sha256"] = digest_bytes((args.output / "manifest.json").read_bytes())
        write_json(args.output / "verification.json", receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(build_dataset(args), ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
