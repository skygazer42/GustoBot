"""Candidate identities and serialization cannot mix concepts, entities or spaces."""

import importlib
import importlib.util
from typing import TypedDict

import pytest

from gustobot.domain.linking import CandidateKind, ReferenceKind


class CatalogIdentityFixture(TypedDict):
    domain_id: str
    ontology_version: str
    ontology_fingerprint: str
    kind: CandidateKind
    ref_kind: ReferenceKind
    object_type: str


class NamedCatalogFixture(CatalogIdentityFixture):
    ref_id: str
    label: str
    source_labels: list[str]
    graph_revision: int


def contracts():
    assert (
        importlib.util.find_spec("gustobot.domain.linking") is not None
    ), "Candidate linking contracts are missing"
    return importlib.import_module("gustobot.domain.linking")


def make(**updates):
    return contracts().CatalogRecord.create(
        domain_id="recipes",
        ontology_version="2026-11-16.3",
        ontology_fingerprint="a" * 64,
        kind="entity",
        ref_kind="entity",
        ref_id=updates.pop("ref_id", "recipe-1"),
        object_type="RecipeVariant",
        label=updates.pop("label", "佛跳墙"),
        **updates,
    )


def test_candidate_kind_cannot_substitute_entity_id_for_concept():
    module = contracts()
    record = make()
    with pytest.raises(ValueError, match="kind"):
        module.CatalogRecord.model_validate(record.model_dump() | {"kind": "concept"})
    assert make(ref_id="recipe-2").record_id != record.record_id


def test_index_scope_requires_model_and_embedding_identity():
    module = contracts()
    scope = module.IndexScope(
        domain_id="recipes",
        ontology_version="v1",
        ontology_fingerprint="a" * 64,
        embedding_fingerprint="b" * 64,
        kind="entity",
    )
    assert scope.key != scope.model_copy(update={"kind": "concept"}).key
    with pytest.raises(ValueError):
        module.IndexScope.model_validate(scope.model_dump() | {"embedding_fingerprint": ""})
    assert (
        module.GraphRevision(
            domain_id="recipes",
            ontology_version="v1",
            ontology_fingerprint="a" * 64,
            state="uninitialized",
        ).revision
        is None
    )
    with pytest.raises(ValueError):
        module.GraphRevision(
            domain_id="recipes", ontology_version="v1", ontology_fingerprint="a" * 64, state="ready"
        )


def test_hash_changes_only_for_the_corresponding_text_or_record_change():
    first = make(aliases=["满坛香", "福寿全"], source_ids=["source-a"])
    reordered = make(aliases=["福寿全", "满坛香"], source_ids=["source-a"])
    linked = make(aliases=["满坛香", "福寿全"], source_ids=["source-b"])
    changed = make(label="家庭版佛跳墙", aliases=["满坛香", "福寿全"], source_ids=["source-a"])
    assert first == reordered
    assert linked.record_id == first.record_id and linked.text_hash == first.text_hash
    assert linked.record_hash != first.record_hash
    assert changed.text_hash != first.text_hash
    assert len(make(label="菜" * 3000).text) == 2048


def test_scope_checks_reject_cross_domain_and_old_ontology_records():
    module = contracts()
    scope = module.IndexScope(
        domain_id="recipes",
        ontology_version="2026-11-16.3",
        ontology_fingerprint="a" * 64,
        embedding_fingerprint="b" * 64,
        kind="entity",
    )
    scope.validate_record(make())
    with pytest.raises(ValueError, match="scope"):
        scope.validate_record(make().model_copy(update={"domain_id": "equipment"}))


def test_real_hash_validation_rejects_metadata_tampering():
    module = contracts()
    payload = make().model_dump() | {"label": "篡改名称"}
    with pytest.raises(ValueError, match="hash"):
        module.CatalogRecord.model_validate(payload)


def test_long_candidate_text_reports_truncation():
    from gustobot.domain.linking import CatalogRecord

    item = CatalogRecord.create(
        domain_id="recipes",
        ontology_version="v3",
        ontology_fingerprint="a" * 64,
        kind="concept",
        ref_kind="class",
        ref_id="urn:recipe",
        object_type="RecipeVariant",
        label="菜谱",
        description="说明" * 2000,
    )
    assert len(item.text) == 2048
    assert item.text_truncated is True


def test_embedding_text_normalizes_names_without_rewriting_display_or_identity():
    from gustobot.domain.linking import CatalogRecord

    common: CatalogIdentityFixture = {
        "domain_id": "recipes",
        "ontology_version": "v3",
        "ontology_fingerprint": "a" * 64,
        "kind": "entity",
        "ref_kind": "entity",
        "object_type": "RecipeVariant",
    }
    first = CatalogRecord.create(
        **common, ref_id="source-a", label="ＲＥＣＩＰＥ　A", aliases=["recipe a", "做法"]
    )
    second = CatalogRecord.create(**common, ref_id="source-b", label="recipe a", aliases=["做法"])
    assert first.text_hash == second.text_hash
    assert first.record_id != second.record_id
    assert first.label == "ＲＥＣＩＰＥ　A"


def test_highly_shared_entity_provenance_is_bounded_and_auditable():
    import json

    from gustobot.domain.linking import CatalogRecord, digest

    sources = ["source-" + str(index).zfill(5) + "a" * 60 for index in range(20000)]
    labels = ["https://recipes.example/" + str(index).zfill(5) for index in range(20000)]
    common: NamedCatalogFixture = {
        "domain_id": "recipes",
        "ontology_version": "v3",
        "ontology_fingerprint": "a" * 64,
        "kind": "entity",
        "ref_kind": "entity",
        "object_type": "Flavor",
        "ref_id": "flavor-id",
        "label": "咸鲜",
        "source_labels": labels,
        "graph_revision": 1,
    }
    item = CatalogRecord.create(**common, source_ids=sources)
    assert item.source_count == 20000
    assert len(item.source_ids) == 8
    assert len(item.source_labels) == 3
    assert item.source_ids_hash == digest(sorted(sources))
    assert len(json.dumps(item.model_dump(), ensure_ascii=False).encode()) < 65535
    other = CatalogRecord.create(**common, source_ids=[*sources[:-1], "zz-new-source"])
    assert other.text_hash == item.text_hash
    assert other.record_hash != item.record_hash
