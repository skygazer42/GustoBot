"""校验并应用逐菜查证的修订，保留原始来源、审查问题与补充证据。"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_EDITABLE_FIELDS = frozenset(
    {
        "description",
        "ingredients",
        "steps",
        "tips",
        "categories",
        "cuisines",
        "durations",
        "servings",
        "tags",
        "images",
    }
)
_IMAGE_DERIVED_FIELDS = frozenset(
    {"validation_status", "local_path", "sha256", "width", "height", "error"}
)


class CorrectionModel(BaseModel):
    """对人工修订文件实行严格契约，避免拼错字段被静默忽略。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class CorrectionReference(CorrectionModel):
    """把官方指南、原始作者与其他配方版本分开记录。"""

    id: str
    url: str
    title: str
    kind: Literal["original_source", "official_guidance", "original_author", "recipe_variant"]
    access: Literal["full_text", "search_excerpt", "blocked"]
    supports: list[str]


class IssueResolution(CorrectionModel):
    """每一项实际修订必须追溯到审查问题、修改字段及证据。"""

    audit_issue_indexes: list[int] = Field(min_length=1)
    action: Literal[
        "corrected", "removed_unsupported_claim", "retained_variant", "documented_condition"
    ]
    paths: list[str] = Field(min_length=1)
    reference_ids: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1)


class RecipeCorrection(CorrectionModel):
    """对冻结整条记录的有条件替换，不能改写原文或来源身份。"""

    row: int = Field(ge=1)
    id: str
    name: str
    original_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replace: dict[str, Any]
    resolutions: list[IssueResolution] = Field(min_length=1)
    remaining_limitations: list[str]

    @model_validator(mode="after")
    def check_fields(self) -> RecipeCorrection:
        """替换集合必须明确且包含补充后的描述，保护原始证据字段。"""
        if not self.replace or set(self.replace) - _EDITABLE_FIELDS:
            raise ValueError("Correction contains an empty or prohibited replacement")
        if "description" not in self.replace:
            raise ValueError("Each reviewed recipe must provide its corrected description")
        return self


class CorrectionRange(CorrectionModel):
    """分片物理行号用于人工核对，实际应用始终按稳定 ID。"""

    start: int = Field(ge=1)
    end: int = Field(ge=1)


class CorrectionBatch(CorrectionModel):
    """同一批原始记录上的完整修订及其引用清单。"""

    batch: CorrectionRange
    references: list[CorrectionReference] = Field(min_length=1)
    recipes: list[RecipeCorrection] = Field(min_length=1)


class RegisteredCorrection(CorrectionModel):
    """把一组修订文件与其冻结的原审查范围绑定。"""

    id: str
    directory: str
    audit_directory: str
    enabled: bool


class CorrectionRegistry(CorrectionModel):
    """显式启用已完成的批次，避免发布仅写了一半的修订。"""

    schema_version: Literal[1]
    batches: list[RegisteredCorrection]


class RecipeCuration(CorrectionModel):
    """保留资料修订版本及边界，不把文献复核冒称为烹饪实测。"""

    batch_id: str
    correction_sha256: str
    original_record_sha256: str
    audit_row: int
    applied_fields: list[str]
    references: list[CorrectionReference]
    resolutions: list[IssueResolution]
    remaining_limitations: list[str]
    supplemental_content_license_status: Literal["reference_only", "review_required"] = (
        "reference_only"
    )
    cooking_tested: Literal[False] = False
    accuracy_certified: Literal[False] = False


def record_digest(record: Any) -> str:
    """计算与冻结审查一致的规范 JSON 摘要，不受字典键顺序影响。"""
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _authored_content(record: dict) -> dict:
    """比较来源内容，排除随图片下载或报告重算产生的派生字段。"""
    result = copy.deepcopy(record)
    for field in ("curation", "nutrition", "quality_flags", "content_sha256"):
        result.pop(field, None)
    result["images"] = [
        {key: value for key, value in image.items() if key not in _IMAGE_DERIVED_FIELDS}
        for image in record["images"]
    ]
    return result


def _replace_fields(current: dict, replacement: dict) -> dict:
    """应用语义修订，同时保留本轮真实图片下载回执。"""
    updated = copy.deepcopy(current)
    for field, value in replacement.items():
        if field != "images":
            updated[field] = copy.deepcopy(value)
            continue
        original_images = {image["url"]: image for image in current["images"]}
        if not isinstance(value, list) or [image["url"] for image in value] != [
            image["url"] for image in current["images"]
        ]:
            raise ValueError("Image corrections may not add, remove or reorder source images")
        images = []
        for proposed in value:
            image = copy.deepcopy(proposed)
            original = original_images[image["url"]]
            immutable = set(original) - _IMAGE_DERIVED_FIELDS - {"role", "step_index", "alt"}
            if any(image[key] != original[key] for key in immutable):
                raise ValueError(
                    "Image evidence and licensing may not be rewritten by semantic corrections"
                )
            for key in _IMAGE_DERIVED_FIELDS:
                image[key] = original[key]
            # 无法从照片和原文证实步骤号时，必须撤销虚构的关联。
            if image["role"] != "step" and image["step_index"] is not None:
                raise ValueError("A non-step image may not retain a step index")
            images.append(image)
        updated[field] = images
    return updated


def _bounded_path(base: Path, value: str, boundary: Path) -> Path:
    """登记路径须留在数据集目录，不能读取任意外部审查文件。"""
    target = (base / value).resolve()
    if not target.is_relative_to(boundary.resolve()):
        raise ValueError("Correction registry path escapes the dataset directory")
    return target


def apply_recipe_corrections(
    records: list[dict], registry_path: Path | None
) -> tuple[list[dict], dict]:
    """按 ID 应用全部启用批次，并验证冻结摘要和逐问题解决覆盖。"""
    if registry_path is None:
        return records, {
            "enabled_batches": [],
            "corrected_recipes": 0,
            "resolved_issue_records": 0,
            "source_files": [],
        }
    registry = CorrectionRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
    base = registry_path.resolve().parent
    boundary = base.parent
    by_id = {record["id"]: copy.deepcopy(record) for record in records}
    if len(by_id) != len(records):
        raise ValueError("Cannot apply corrections to duplicate recipe identities")
    applied_ids = set()
    batch_ids = []
    source_files = [
        {
            "path": registry_path.as_posix(),
            "sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        }
    ]
    resolved_count = 0
    for registered in registry.batches:
        if not registered.enabled:
            continue
        directory = _bounded_path(base, registered.directory, boundary)
        audit = _bounded_path(base, registered.audit_directory, boundary)
        scope = json.loads((audit / "scope.json").read_text(encoding="utf-8"))
        input_bytes = (audit / "input.jsonl").read_bytes()
        if hashlib.sha256(input_bytes).hexdigest() != scope["input_sha256"]:
            raise ValueError("Frozen audit input checksum does not match its scope")
        with (audit / "input.jsonl").open(encoding="utf-8") as stream:
            frozen_records = [json.loads(line) for line in stream]
        frozen = {record["id"]: record for record in frozen_records}
        rows = {
            record["id"]: scope["start_row"] + index for index, record in enumerate(frozen_records)
        }
        reviews = {
            review["id"]: review
            for review in json.loads((audit / "recipes-review.json").read_text(encoding="utf-8"))
        }
        files = sorted(directory.glob("batch-*.json"))
        if not files:
            raise ValueError("Enabled correction batch has no correction files")
        registered_ids = set()
        for path in files:
            payload_bytes = path.read_bytes()
            batch = CorrectionBatch.model_validate_json(payload_bytes)
            source_files.append(
                {"path": path.as_posix(), "sha256": hashlib.sha256(payload_bytes).hexdigest()}
            )
            references = {reference.id: reference for reference in batch.references}
            if len(references) != len(batch.references):
                raise ValueError("Correction evidence IDs must be unique within a shard")
            if sorted(recipe.row for recipe in batch.recipes) != list(
                range(batch.batch.start, batch.batch.end + 1)
            ):
                raise ValueError("Correction shard does not cover its declared physical rows")
            for correction in batch.recipes:
                if (
                    correction.id in applied_ids
                    or correction.id not in by_id
                    or correction.id not in frozen
                ):
                    raise ValueError(f"Missing or duplicate correction identity: {correction.id}")
                original = frozen[correction.id]
                if correction.name != original["name"] or correction.row != rows[correction.id]:
                    raise ValueError("Correction ID, name and frozen row do not agree")
                if record_digest(original) != correction.original_record_sha256:
                    raise ValueError(f"Correction precondition checksum failed: {correction.id}")
                expected_issues = set(range(len(reviews[correction.id]["issues"])))
                resolved = {
                    index
                    for resolution in correction.resolutions
                    for index in resolution.audit_issue_indexes
                }
                if resolved != expected_issues:
                    raise ValueError(
                        f"Correction does not resolve every audited issue: {correction.id}"
                    )
                used = {
                    reference_id
                    for resolution in correction.resolutions
                    for reference_id in resolution.reference_ids
                }
                if not used.issubset(references):
                    raise ValueError("Correction refers to an unknown evidence ID")
                if not any(references[key].access == "full_text" for key in used):
                    raise ValueError(
                        "Correction needs actually read evidence, not only search excerpts"
                    )
                correction_hash = record_digest(
                    {
                        "recipe": correction.model_dump(),
                        "references": [references[key].model_dump() for key in sorted(used)],
                    }
                )
                current = by_id[correction.id]
                existing = current.get("curation")
                if existing is not None:
                    if existing["correction_sha256"] != correction_hash:
                        raise ValueError(
                            "Rebuild from original source before changing a curated version"
                        )
                    expected = _replace_fields(current, correction.replace)
                    if _authored_content(expected) != _authored_content(current):
                        raise ValueError(
                            "Previously curated fields were edited outside their correction"
                        )
                else:
                    if _authored_content(current) != _authored_content(original):
                        raise ValueError(
                            f"Original source content has changed since review: {correction.id}"
                        )
                    current = _replace_fields(current, correction.replace)
                curation = RecipeCuration(
                    batch_id=registered.id,
                    correction_sha256=correction_hash,
                    original_record_sha256=correction.original_record_sha256,
                    audit_row=correction.row,
                    applied_fields=sorted(correction.replace),
                    references=[references[key] for key in sorted(used)],
                    resolutions=correction.resolutions,
                    remaining_limitations=correction.remaining_limitations,
                    supplemental_content_license_status=(
                        "review_required"
                        if any(
                            references[key].kind in {"original_author", "recipe_variant"}
                            for key in used
                        )
                        else "reference_only"
                    ),
                )
                current["curation"] = curation.model_dump()
                by_id[correction.id] = current
                applied_ids.add(correction.id)
                registered_ids.add(correction.id)
                resolved_count += len(resolved)
        if registered_ids != set(frozen):
            raise ValueError("Enabled correction set must cover every record in its frozen audit")
        batch_ids.append(registered.id)
    return [by_id[record["id"]] for record in records], {
        "enabled_batches": batch_ids,
        "corrected_recipes": len(applied_ids),
        "resolved_issue_records": resolved_count,
        "source_files": source_files,
        "cooking_tested": False,
        "accuracy_certified": False,
    }
