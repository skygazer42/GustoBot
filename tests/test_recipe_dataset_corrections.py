"""逐菜修订必须绑定冻结内容、完整问题覆盖及实际查阅的证据。"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.recipe_dataset_corrections import apply_recipe_corrections, record_digest


def correction_fixture(tmp_path: Path) -> tuple[list[dict], Path, Path]:
    """建立一条有原图回执和两项待修问题的独立修订批次。"""
    root = tmp_path / "recipes"
    audit = root / "audits" / "first"
    directory = root / "corrections" / "first"
    audit.mkdir(parents=True)
    directory.mkdir(parents=True)
    record: dict[str, Any] = {
        "id": "recipe:1",
        "name": "鸡蛋",
        "description": "未经核算的热量100大卡",
        "ingredients": [{"name": "筷子", "amount": None, "unit": None, "role": "unspecified"}],
        "steps": ["打散鸡蛋"],
        "tips": [],
        "quality_flags": [],
        "content_sha256": "old",
        "images": [
            {
                "url": "https://example.org/egg.jpg",
                "role": "step",
                "step_index": 1,
                "alt": "鸡蛋",
                "source_url": "https://example.org/recipe",
                "license": "unknown",
                "license_status": "review_required",
                "validation_status": "verified",
                "local_path": "media/egg.jpg",
                "sha256": "a" * 64,
                "width": 100,
                "height": 100,
                "error": None,
            }
        ],
    }
    body = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    (audit / "input.jsonl").write_bytes(body)
    import hashlib

    (audit / "scope.json").write_text(
        json.dumps({"start_row": 1, "input_sha256": hashlib.sha256(body).hexdigest()}),
        encoding="utf-8",
    )
    (audit / "recipes-review.json").write_text(
        json.dumps(
            [{"id": "recipe:1", "issues": [{"path": "ingredients"}, {"path": "description"}]}]
        ),
        encoding="utf-8",
    )
    image = copy.deepcopy(record["images"][0])
    image.update(role="hero", step_index=None)
    patch = {
        "batch": {"start": 1, "end": 1},
        "references": [
            {
                "id": "source",
                "url": "https://example.org/source",
                "title": "原作者",
                "kind": "original_author",
                "access": "full_text",
                "supports": ["食材与做法"],
            }
        ],
        "recipes": [
            {
                "row": 1,
                "id": "recipe:1",
                "name": "鸡蛋",
                "original_record_sha256": record_digest(record),
                "replace": {
                    "description": "鸡蛋制成的菜肴。",
                    "ingredients": [
                        {"name": "鸡蛋", "amount": "1个", "unit": None, "role": "unspecified"}
                    ],
                    "images": [image],
                },
                "resolutions": [
                    {
                        "audit_issue_indexes": [0, 1],
                        "action": "corrected",
                        "paths": ["description", "ingredients"],
                        "reference_ids": ["source"],
                        "explanation": "补回作者用量并纠正描述。",
                    }
                ],
                "remaining_limitations": ["未实际下厨测试"],
            }
        ],
    }
    path = directory / "batch-01-01.json"
    path.write_text(json.dumps(patch, ensure_ascii=False), encoding="utf-8")
    registry = directory.parent / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "batches": [
                    {
                        "id": "first-v1",
                        "directory": "first",
                        "audit_directory": "../audits/first",
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return [record], registry, path


def change_patch(path: Path, change) -> None:
    """在测试边界修改补丁文件，不改变冻结源记录。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    change(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_correction_replaces_real_content_and_preserves_input(tmp_path: Path) -> None:
    """修订改变菜谱内容并保存来源链，不原地破坏待审原文。"""
    records, registry, _ = correction_fixture(tmp_path)
    corrected, report = apply_recipe_corrections(records, registry)
    assert records[0]["ingredients"][0]["name"] == "筷子"
    assert corrected[0]["ingredients"][0]["name"] == "鸡蛋"
    assert corrected[0]["curation"]["original_record_sha256"] == record_digest(records[0])
    assert corrected[0]["curation"]["cooking_tested"] is False
    assert report["corrected_recipes"] == 1
    assert report["resolved_issue_records"] == 2
    assert corrected[0]["images"][0]["sha256"] == "a" * 64


def test_reapplying_same_correction_is_idempotent(tmp_path: Path) -> None:
    """同一修订重复应用不继续添加元数据或改变内容身份。"""
    records, registry, _ = correction_fixture(tmp_path)
    first, _ = apply_recipe_corrections(records, registry)
    second, _ = apply_recipe_corrections(first, registry)
    assert first == second


def test_changed_original_source_cannot_be_silently_corrected(tmp_path: Path) -> None:
    """来源修改后旧审查不得无条件覆盖新版本。"""
    records, registry, _ = correction_fixture(tmp_path)
    records[0]["steps"] = ["不同的烹饪步骤"]
    with pytest.raises(ValueError, match="changed since review"):
        apply_recipe_corrections(records, registry)


def test_precondition_checksum_is_enforced(tmp_path: Path) -> None:
    """修订前置摘要必须与真正冻结的整条记录相同。"""
    records, registry, path = correction_fixture(tmp_path)
    change_patch(
        path, lambda payload: payload["recipes"][0].update(original_record_sha256="b" * 64)
    )
    with pytest.raises(ValueError, match="checksum"):
        apply_recipe_corrections(records, registry)


def test_all_audited_issues_must_be_covered(tmp_path: Path) -> None:
    """不能把漏修的问题用一个批次通过状态掩盖。"""
    records, registry, path = correction_fixture(tmp_path)
    change_patch(
        path,
        lambda payload: payload["recipes"][0]["resolutions"][0].update(audit_issue_indexes=[0]),
    )
    with pytest.raises(ValueError, match="every audited issue"):
        apply_recipe_corrections(records, registry)


def test_unknown_reference_and_unread_evidence_are_rejected(tmp_path: Path) -> None:
    """来源引用须闭合，只有搜索摘要不能当作已读全文。"""
    records, registry, path = correction_fixture(tmp_path)
    change_patch(path, lambda payload: payload["references"][0].update(access="search_excerpt"))
    with pytest.raises(ValueError, match="actually read evidence"):
        apply_recipe_corrections(records, registry)
    change_patch(
        path,
        lambda payload: payload["recipes"][0]["resolutions"][0].update(reference_ids=["missing"]),
    )
    with pytest.raises(ValueError, match="unknown evidence"):
        apply_recipe_corrections(records, registry)


def test_image_semantics_keep_current_download_state(tmp_path: Path) -> None:
    """关闭图片下载的重建不沿用上次的已验证图片状态。"""
    records, registry, _ = correction_fixture(tmp_path)
    records[0]["images"][0].update(
        validation_status="not_downloaded", local_path=None, sha256=None, width=None, height=None
    )
    corrected, _ = apply_recipe_corrections(records, registry)
    assert corrected[0]["images"][0]["role"] == "hero"
    assert corrected[0]["images"][0]["validation_status"] == "not_downloaded"
    assert corrected[0]["images"][0]["sha256"] is None


def test_image_license_cannot_be_rewritten_as_semantic_fix(tmp_path: Path) -> None:
    """图片角色修订不能悄悄更换第三方图片许可证。"""
    records, registry, path = correction_fixture(tmp_path)
    change_patch(
        path, lambda payload: payload["recipes"][0]["replace"]["images"][0].update(license="CC0")
    )
    with pytest.raises(ValueError, match="licensing"):
        apply_recipe_corrections(records, registry)


def test_protected_source_fields_cannot_be_replaced(tmp_path: Path) -> None:
    """新版本保留原作者及原始记录，不伪造已经修过的上游文本。"""
    records, registry, path = correction_fixture(tmp_path)
    change_patch(
        path, lambda payload: payload["recipes"][0]["replace"].update(source={"url": "elsewhere"})
    )
    with pytest.raises(ValueError, match="prohibited"):
        apply_recipe_corrections(records, registry)


def test_disabled_batch_and_absent_registry_are_noops(tmp_path: Path) -> None:
    """未启用的半成品批次不改变任何记录。"""
    records, registry, _ = correction_fixture(tmp_path)
    corrected, report = apply_recipe_corrections(records, None)
    assert corrected == records and report["corrected_recipes"] == 0
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["batches"][0]["enabled"] = False
    registry.write_text(json.dumps(payload), encoding="utf-8")
    corrected, report = apply_recipe_corrections(records, registry)
    assert corrected == records and report["corrected_recipes"] == 0
