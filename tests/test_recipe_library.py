"""The public recipe catalog reads real records without an index or admin session."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI


def recipe_record(recipe_id="recipe-a", name="青椒土豆丝", **changes):
    record = {
        "id": recipe_id,
        "name": name,
        "description": "保留原文说明",
        "ingredients": [{"name": "土豆", "amount": None, "unit": None, "role": "main"}],
        "steps": ["切丝。", "炒熟。"],
        "tips": ["原文未注明用量。"],
        "categories": ["素菜"],
        "cuisines": [],
        "tags": ["家常"],
        "servings": None,
        "durations": {"prep": None, "cook": None, "total": None},
        "images": [],
        "source": {
            "provider": "HowToCook",
            "record_id": "dishes/a.md",
            "url": "https://example.org/a",
            "original_url": None,
            "license": "Unlicense",
            "license_url": "https://example.org/LICENSE",
            "license_status": "repository_declared",
            "attribution": "Original contributors",
            "revision": "revision-a",
        },
        "content_sha256": "ingredients-and-steps-only",
    }
    record.update(changes)
    return record


def write_catalog(path: Path, records):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")


def image_record(filename, *, role="hero", status="verified", **changes):
    record = {
        "url": "https://images.example.org/original.jpg",
        "local_path": f"media/{filename}",
        "role": role,
        "step_index": 1 if role == "step" else None,
        "alt": "原方配图",
        "license": "Unlicense",
        "license_status": "repository_declared",
        "source_url": "https://example.org/a",
        "author": None,
        "validation_status": status,
        "width": 640,
        "height": 480,
    }
    record.update(changes)
    return record


@pytest.fixture
def catalog_api(tmp_path):
    from gustobot.application.services.recipe_library import (
        RecipeLibrary,
        get_recipe_library,
    )
    from gustobot.interfaces.http.recipe_router import router

    path = tmp_path / "recipes.jsonl"
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    library = RecipeLibrary(path)
    app.dependency_overrides[get_recipe_library] = lambda: library
    return app, path, library


@pytest.mark.asyncio
async def test_search_categories_pagination_and_actual_nullable_details(catalog_api):
    app, path, _ = catalog_api
    write_catalog(
        path,
        [
            recipe_record(),
            recipe_record("recipe-b", "清蒸鱼", categories=["荤菜"], tags=["清淡"]),
            recipe_record("recipe-c", "土豆炖肉", categories=["荤菜"]),
        ],
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = (await client.get("/api/v1/recipes", params={"q": "土豆 家常", "limit": 1})).json()
        assert result["total"] == 2 and len(result["items"]) == 1
        assert result["categories"] == [{"name": "素菜", "count": 1}, {"name": "荤菜", "count": 2}]
        assert len(result["dataset_version"]) == 64
        filtered = (await client.get("/api/v1/recipes", params={"category": "素菜"})).json()
        assert filtered["total"] == 1 and filtered["items"][0]["id"] == "recipe-a"
        paged = (await client.get("/api/v1/recipes", params={"offset": 2, "limit": 1})).json()
        assert len(paged["items"]) == 1 and paged["offset"] == 2
        assert (await client.get("/api/v1/recipes", params={"q": "不存在"})).json()["items"] == []
        detail = (await client.get("/api/v1/recipes/recipe-a")).json()
        assert detail["name"] == "青椒土豆丝" and detail["steps"] == ["切丝。", "炒熟。"]
        assert detail["servings"] is None and detail["servings_count"] is None
        assert detail["ingredients"][0]["amount"] is None
        assert detail["durations"] == {"prep": None, "cook": None, "total": None}
        assert detail["source"]["attribution"] == "Original contributors"
        assert (await client.get("/api/v1/recipes/missing")).status_code == 404


@pytest.mark.asyncio
async def test_empty_category_matches_unfiltered_catalog_for_frontend_query(catalog_api):
    app, path, _ = catalog_api
    write_catalog(path, [recipe_record(), recipe_record("recipe-b", "清蒸鱼", categories=["荤菜"])])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        expected = await client.get("/api/v1/recipes", params={"offset": 0, "limit": 12})
        response = await client.get("/api/v1/recipes?q=&category=&offset=0&limit=12")
    assert response.status_code == 200
    assert response.json() == expected.json()
    assert response.json()["total"] == 2


@pytest.mark.asyncio
async def test_only_referenced_verified_local_images_are_served_and_step_is_not_cover(catalog_api):
    app, path, _ = catalog_api
    media = path.parent / "media"
    media.mkdir()
    for filename in ("hero.jpg", "step.png", "unverified.jpg", "private.jpg"):
        (media / filename).write_bytes(b"image-fixture")
    write_catalog(
        path,
        [
            recipe_record(images=[image_record("step.png", role="step")]),
            recipe_record("recipe-b", "有封面", images=[image_record("hero.jpg")]),
            recipe_record("recipe-c", "缺图", images=[image_record("missing.jpg")]),
            recipe_record(
                "recipe-d", "未验证", images=[image_record("unverified.jpg", status="failed")]
            ),
        ],
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = (await client.get("/api/v1/recipes")).json()
        assert listed["items"][0]["id"] == "recipe-b"
        detail = (await client.get("/api/v1/recipes/recipe-a")).json()
        assert detail["cover_image"] is None
        assert detail["images"][0]["step_index"] == 1
        cover = listed["items"][0]["cover_image"]
        assert cover["url"] == "/api/v1/recipes/media/hero.jpg"
        assert cover["original_url"] == "https://images.example.org/original.jpg"
        assert "local_path" not in json.dumps(detail)
        assert (await client.get(cover["url"])).content == b"image-fixture"
        for filename in ("private.jpg", "unverified.jpg", "missing.jpg", "..%2Frecipes.jsonl"):
            assert (await client.get("/api/v1/recipes/media/" + filename)).status_code == 404
        (media / "hero.jpg").unlink()
        assert (await client.get(cover["url"])).status_code == 404


@pytest.mark.asyncio
async def test_media_escape_and_unsafe_links_are_never_exposed(catalog_api, tmp_path):
    app, path, _ = catalog_api
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"private")
    source = recipe_record()["source"] | {
        "url": "file:///secret",
        "license_url": "javascript:alert(1)",
    }
    write_catalog(path, [recipe_record(source=source, images=[image_record("../outside.jpg")])])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        detail = (await client.get("/api/v1/recipes/recipe-a")).json()
        assert detail["images"] == [] and detail["cover_image"] is None
        assert detail["source"]["url"] is None and detail["source"]["license_url"] is None
        assert (await client.get("/api/v1/recipes/media/outside.jpg")).status_code == 404


def test_media_symlinks_cannot_escape_root(catalog_api, tmp_path):
    _, path, library = catalog_api
    media = path.parent / "media"
    media.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"private")
    try:
        (media / "escape.jpg").symlink_to(outside)
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links")
    write_catalog(path, [recipe_record(images=[image_record("escape.jpg")])])
    assert library.get("recipe-a").images == []


def test_symlinked_media_directory_cannot_escape_dataset_directory(catalog_api, tmp_path):
    _, path, library = catalog_api
    outside = tmp_path / "outside-media"
    outside.mkdir()
    (outside / "escape.jpg").write_bytes(b"private")
    try:
        (path.parent / "media").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links")
    write_catalog(path, [recipe_record(images=[image_record("escape.jpg")])])
    assert library.get("recipe-a").images == []


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 49}, {"offset": -1}, {"q": "x" * 201}])
async def test_public_query_constraints_are_http_validation_errors(catalog_api, params):
    app, path, _ = catalog_api
    write_catalog(path, [recipe_record()])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/recipes", params=params)).status_code == 422


@pytest.mark.asyncio
async def test_missing_and_corrupt_catalog_is_unavailable_without_fake_recipe(catalog_api):
    app, path, _ = catalog_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/recipes")).status_code == 503
        for content in ("not json", '{"id":"broken"}', "[]"):
            path.write_text(content, encoding="utf-8")
            assert (await client.get("/api/v1/recipes")).status_code == 503


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("2", 2),
        (" 2人份 ", 2),
        ("3份", 3),
        ("4人", 4),
        ("2-3人", None),
        ("1批", None),
        ("0", None),
    ],
)
def test_servings_only_parse_unambiguous_positive_counts(catalog_api, value, expected):
    _, path, library = catalog_api
    write_catalog(path, [recipe_record(servings=value)])
    assert library.get("recipe-a").servings_count == expected


def test_full_record_version_and_cached_snapshot_invalidation(catalog_api):
    _, path, library = catalog_api
    raw = recipe_record()
    write_catalog(path, [raw])
    first = library.get("recipe-a")
    expected = hashlib.sha256(
        json.dumps(
            raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    assert first.version == expected
    raw["tips"] = ["新的提示也应改变版本，即使食材和步骤指纹不变。"]
    write_catalog(path, [raw])
    assert library.get("recipe-a").version != first.version
    path.write_text("broken replacement", encoding="utf-8")
    from gustobot.application.services.recipe_library import RecipeLibraryUnavailable

    with pytest.raises(RecipeLibraryUnavailable):
        library.get("recipe-a")


def test_empty_quantity_tip_headings_are_filtered_only_in_public_projection(catalog_api):
    _, path, library = catalog_api
    meaningful = [
        "用量说明：每次制作前重新确定用量，一份正好够2个人吃。",
        "每份：2人",
        "用量说明：每份：2人",
        "用量说明: 500g",
        "保持小火。",
    ]
    empty_headings = ["用量说明：每份：", "用量说明", "每份：", " 用量说明: 每份: "]
    raw = recipe_record(tips=[*meaningful, *empty_headings])
    write_catalog(path, [raw])
    original_bytes = path.read_bytes()
    first = library.get("recipe-a")
    assert first.tips == meaningful
    expected = hashlib.sha256(
        json.dumps(
            raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    assert first.version == expected and path.read_bytes() == original_bytes
    raw["tips"] = meaningful
    write_catalog(path, [raw])
    without_headings = library.get("recipe-a")
    assert without_headings.tips == meaningful
    assert without_headings.version != first.version
