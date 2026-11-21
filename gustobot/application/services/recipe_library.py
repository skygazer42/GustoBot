"""Read-only public recipe catalog backed by the licensed offline JSONL dataset."""

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from gustobot.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
EMPTY_QUANTITY_HEADING = re.compile(r"\s*(?:(?:用量说明|每份)\s*[:：]?\s*)+")


class RecipeLibraryUnavailable(RuntimeError):
    """The configured dataset cannot currently supply a valid snapshot."""


class RecipeNotFound(LookupError):
    """The current snapshot does not contain the requested recipe or image."""


class RecipeSource(BaseModel):
    """Original attribution; only HTTP(S) URLs are exposed as clickable links."""

    model_config = ConfigDict(strict=True)

    provider: str
    record_id: str
    url: str | None
    original_url: str | None = None
    license: str | None
    license_url: str | None = None
    license_status: str
    attribution: str | None
    revision: str | None = None

    @field_validator("url", "original_url", "license_url")
    @classmethod
    def web_link(cls, value: str | None) -> str | None:
        """Keep absent or unsafe source addresses out of public navigation."""
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
                return value
        except ValueError:
            pass
        return None


class RecipeImage(BaseModel):
    """A verified local image plus its actual upstream role and provenance."""

    model_config = ConfigDict(strict=True)

    url: str
    original_url: str | None
    source_url: str | None
    alt: str
    role: Literal["hero", "step", "unspecified"]
    step_index: int | None = Field(default=None, ge=1)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    license: str | None
    license_status: str
    author: str | None = None


class RecipeDurations(BaseModel):
    """Unmodified duration expressions; absence remains unknown."""

    model_config = ConfigDict(strict=True)

    prep: str | None = None
    cook: str | None = None
    total: str | None = None


class RecipeIngredient(BaseModel):
    """One ingredient with its original quantity rather than an estimated number."""

    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1)
    amount: str | None = None
    unit: str | None = None
    role: str


class RecipeSummary(BaseModel):
    """Fields required to choose a recipe from the public catalog."""

    id: str
    version: str
    name: str
    categories: list[str]
    cuisines: list[str]
    tags: list[str]
    ingredient_names: list[str]
    step_count: int
    servings: str | None
    servings_count: int | None
    durations: RecipeDurations
    cover_image: RecipeImage | None
    source: RecipeSource


class RecipeDetail(RecipeSummary):
    """The complete source recipe available for reading and grounded questions."""

    description: str | None
    ingredients: list[RecipeIngredient]
    steps: list[str]
    tips: list[str]
    images: list[RecipeImage]


class RecipeCategory(BaseModel):
    """One category counted over the entire catalog, before search and paging."""

    name: str
    count: int


class RecipePage(BaseModel):
    """A bounded catalog page and the identity of its current dataset snapshot."""

    items: list[RecipeSummary]
    total: int
    offset: int
    limit: int
    categories: list[RecipeCategory]
    dataset_version: str


class _DatasetImage(BaseModel):
    """Only dataset fields needed to admit an image into the public catalog."""

    model_config = ConfigDict(strict=True)

    url: str
    local_path: str | None = None
    validation_status: str
    role: Literal["hero", "step", "unspecified"]
    step_index: int | None = Field(default=None, ge=1)
    alt: str = ""
    license: str | None
    license_status: str
    source_url: str | None
    author: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)


class _DatasetRecipe(BaseModel):
    """Validate the consumed dataset fields without importing build-time tooling."""

    model_config = ConfigDict(strict=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    ingredients: list[RecipeIngredient] = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    tips: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    cuisines: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    servings: str | None = None
    durations: RecipeDurations = Field(default_factory=RecipeDurations)
    images: list[_DatasetImage] = Field(default_factory=list)
    source: RecipeSource

    @field_validator("steps")
    @classmethod
    def nonblank_steps(cls, value: list[str]) -> list[str]:
        """A blank step is corrupt data, not an empty-result search."""
        if any(not step.strip() for step in value):
            raise ValueError("Recipe steps must not be blank")
        return value


@dataclass(frozen=True)
class _Snapshot:
    """One cached dataset read, shared by list, detail, and media requests."""

    fingerprint: tuple[int, int]
    version: str
    details: dict[str, RecipeDetail]
    summaries: list[RecipeSummary]
    categories: list[RecipeCategory]
    media: dict[str, Path]


def _servings_count(value: str | None) -> int | None:
    """Parse only a positive whole-number serving count explicitly in the source."""
    if value is None:
        return None
    match = re.fullmatch(r"([1-9][0-9]*)\s*(?:人份|人|份)?", value.strip())
    return None if match is None else int(match[1])


class RecipeLibrary:
    """Own the cached file snapshot and the boundary around its image directory."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.media_root = self.path.parent / "media"
        self._snapshot: _Snapshot | None = None
        self._lock = Lock()

    def _image_path(self, local_path: str) -> Path | None:
        candidate = self.path.parent / local_path
        resolved = candidate.resolve()
        if (
            candidate.parent != self.path.parent / "media"
            or not resolved.is_relative_to(self.media_root)
            or resolved.suffix.lower() not in IMAGE_SUFFIXES
            or not resolved.is_file()
        ):
            return None
        return resolved

    def _read_snapshot(self, fingerprint: tuple[int, int]) -> _Snapshot:
        content = self.path.read_bytes()
        details: dict[str, RecipeDetail] = {}
        media: dict[str, Path] = {}
        counts: Counter[str] = Counter()
        for line in content.decode("utf-8-sig").splitlines():
            if not line.strip():
                continue
            raw: Any = json.loads(line)
            record = _DatasetRecipe.model_validate(raw)
            canonical = json.dumps(
                raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            version = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if record.id in details:
                raise ValueError("Duplicate recipe identity")
            images: list[RecipeImage] = []
            for image in record.images:
                if image.validation_status != "verified" or image.local_path is None:
                    continue
                image_path = self._image_path(image.local_path)
                if image_path is None:
                    continue
                filename = Path(image.local_path).name
                media[filename] = image_path
                images.append(
                    RecipeImage(
                        **image.model_dump(
                            exclude={"url", "local_path", "validation_status", "source_url"}
                        ),
                        url=f"{settings.API_V1_PREFIX}/recipes/media/{quote(filename)}",
                        original_url=RecipeSource.web_link(image.url),
                        source_url=RecipeSource.web_link(image.source_url),
                    )
                )
            cover = next((image for image in images if image.role == "hero"), None)
            if cover is None:
                cover = next((image for image in images if image.role == "unspecified"), None)
            detail = RecipeDetail(
                **record.model_dump(exclude={"images", "tips"}),
                version=version,
                servings_count=_servings_count(record.servings),
                ingredient_names=[ingredient.name for ingredient in record.ingredients],
                step_count=len(record.steps),
                cover_image=cover,
                images=images,
                tips=[tip for tip in record.tips if EMPTY_QUANTITY_HEADING.fullmatch(tip) is None],
            )
            details[record.id] = detail
            counts.update(set(record.categories))
        summaries = [
            RecipeSummary.model_validate(detail.model_dump()) for detail in details.values()
        ]
        summaries.sort(
            key=lambda recipe: (recipe.cover_image is None, recipe.name.casefold(), recipe.id)
        )
        return _Snapshot(
            fingerprint=fingerprint,
            version=hashlib.sha256(content).hexdigest(),
            details=details,
            summaries=summaries,
            categories=[
                RecipeCategory(name=name, count=count) for name, count in sorted(counts.items())
            ],
            media=media,
        )

    def _current(self) -> _Snapshot:
        try:
            with self._lock:
                stat = self.path.stat()
                fingerprint = (stat.st_mtime_ns, stat.st_size)
                if self._snapshot is None or self._snapshot.fingerprint != fingerprint:
                    snapshot = self._read_snapshot(fingerprint)
                    self._snapshot = snapshot
                return self._snapshot
        except (OSError, UnicodeError, ValueError, ValidationError) as exc:
            raise RecipeLibraryUnavailable("菜谱目录暂不可用，请检查数据文件") from exc

    def list(
        self, *, q: str = "", category: str | None = None, offset: int = 0, limit: int = 12
    ) -> RecipePage:
        """Search the current catalog and return one bounded, stable page."""
        snapshot = self._current()
        terms = q.casefold().split()
        matches = []
        for recipe in snapshot.summaries:
            if category not in (None, "") and category not in recipe.categories:
                continue
            search_text = " ".join(
                [recipe.name, *recipe.ingredient_names, *recipe.categories, *recipe.tags]
            ).casefold()
            if all(term in search_text for term in terms):
                matches.append(recipe)
        return RecipePage(
            items=matches[offset : offset + limit],
            total=len(matches),
            offset=offset,
            limit=limit,
            categories=snapshot.categories,
            dataset_version=snapshot.version,
        )

    def get(self, recipe_id: str) -> RecipeDetail:
        """Return the selected recipe without substituting another catalog entry."""
        recipe = self._current().details.get(recipe_id)
        if recipe is None:
            raise RecipeNotFound("菜谱不存在")
        return recipe

    def media_path(self, filename: str) -> Path:
        """Recheck the referenced image before handing it to the file response."""
        path = self._current().media.get(filename)
        if path is None or self._image_path(f"media/{filename}") != path:
            raise RecipeNotFound("图片不存在")
        return path


@lru_cache(maxsize=8)
def _library_for_path(path: str) -> RecipeLibrary:
    return RecipeLibrary(Path(path))


def get_recipe_library() -> RecipeLibrary:
    """Resolve relative dataset configuration against the project, not the process CWD."""
    path = Path(settings.RECIPE_DATASET_PATH)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return _library_for_path(str(path.resolve()))
