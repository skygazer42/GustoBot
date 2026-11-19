"""Actual graph match sources must preserve the deterministic query path."""

import pytest

from gustobot.application.services.entity_linking import EntityLinkingService
from gustobot.application.services.knowledge_query import KnowledgeQueryService
from gustobot.domain.linking import (
    CandidateHit,
    CandidateKind,
    IndexPublicationStatus,
    IndexScope,
    ObjectReference,
)
from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts
from tests.test_linking_catalog import (
    formal_model as formal_model,  # noqa: PLC0414 - pytest fixture
)
from tests.test_linking_catalog import (
    linking_graph as linking_graph,  # noqa: PLC0414 - pytest fixture
)

CANDIDATE_KINDS: tuple[CandidateKind, CandidateKind] = ("concept", "entity")


@pytest.mark.parametrize("mention_kind", ["name", "alias", "id"])
@pytest.mark.asyncio
async def test_real_exact_anchor_and_known_property_need_no_embedding_or_planner(
    linking_graph, mention_kind
):
    scope = linking_graph
    recipe = scope.quick.model_copy(deep=True)
    variant = next(entity for entity in recipe.entities if entity.type == "RecipeVariant")
    variant.aliases.append("家宴坛炖")
    await scope.store.upsert(recipe)
    calls = []

    class Embeddings:
        def embed_query(self, text):
            calls.append(text)
            return [1.0, 0.0]

    class Store:
        def search(self, *args, **kwargs):
            return []

    def publication(index_scope):
        return IndexPublicationStatus(
            scope=index_scope,
            generation_id="exact_integration",
            status="ready",
            graph_revision=1 if index_scope.kind == "entity" else None,
            calibration_id="fixture",
            policy={"min_cosine": 0.8, "margin": 0.05},
        )

    index_scopes: dict[str, IndexScope] = {
        kind: IndexScope(
            domain_id=scope.domain.id,
            ontology_version=scope.domain.version,
            ontology_fingerprint=scope.domain.semantic_model.fingerprint,
            embedding_fingerprint="b" * 64,
            kind=kind,
        )
        for kind in CANDIDATE_KINDS
    }
    linker = EntityLinkingService(
        scope.domain,
        graph_store=scope.store,
        candidate_store=Store(),
        embedder=Embeddings(),
        scopes=index_scopes,
        publication_provider=publication,
        mode="on",
    )
    service = KnowledgeQueryService(
        scope.domain, graph_store=scope.store, documents=None, model=None, linker=linker
    )
    mention = {
        "name": variant.name,
        "alias": "家宴坛炖",
        "id": variant.id,
    }[mention_kind]
    answer = await service.answer(f"{mention}加多少鸡肉？")
    assert answer.metadata["analysis_calls"] == 0
    assert answer.metadata["linking"]["selected_ids"] == [variant.id]
    assert not calls


@pytest.mark.asyncio
async def test_same_name_write_during_planner_invalidates_cached_unique_candidate(
    linking_graph,
):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    page = await scope.store.export_linking_records(limit=100)
    candidate = next(record for record in page.records if record.object_type == "RecipeVariant")
    planner_calls = []
    embedding_calls = []

    class Embeddings:
        def embed_query(self, text):
            embedding_calls.append(text)
            return [1.0, 0.0]

    class Store:
        def search(self, vector, *, scope, generation_id, expected_types, **kwargs):
            if scope.kind == "concept" or expected_types not in [
                (),
                ("RecipeVariant",),
            ]:
                return []
            return [
                CandidateHit(
                    record=candidate,
                    scope=scope,
                    generation_id=generation_id,
                    vector_score=0.95,
                )
            ]

    class Model:
        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            planner_calls.append(messages)
            await scope.store.upsert(scope.slow)
            return {
                "facts": True,
                "entity_type": "RecipeVariant",
                "entity_mentions": ["佛跳牆"],
                "anchor_ids": [candidate.ref_id],
                "requests": [{"property": "ingredientQuantity", "target": "鸡肉"}],
            }

    def publication(index_scope):
        return IndexPublicationStatus(
            scope=index_scope,
            generation_id="planner_race",
            status="ready",
            graph_revision=1 if index_scope.kind == "entity" else None,
            calibration_id="fixture",
            policy={"min_cosine": 0.8, "margin": 0.05},
        )

    index_scopes: dict[str, IndexScope] = {
        kind: IndexScope(
            domain_id=scope.domain.id,
            ontology_version=scope.domain.version,
            ontology_fingerprint=scope.domain.semantic_model.fingerprint,
            embedding_fingerprint="b" * 64,
            kind=kind,
        )
        for kind in CANDIDATE_KINDS
    }
    linker = EntityLinkingService(
        scope.domain,
        graph_store=scope.store,
        candidate_store=Store(),
        embedder=Embeddings(),
        scopes=index_scopes,
        publication_provider=publication,
        mode="on",
    )
    service = KnowledgeQueryService(
        scope.domain,
        graph_store=scope.store,
        documents=None,
        model=Model(),
        linker=linker,
    )
    answer = await service.answer("佛跳牆加多少鸡肉？")
    assert answer.metadata["status"] in {"needs_clarification", "retrieval_unavailable"}
    assert len(planner_calls) == 1
    assert len(embedding_calls) <= 2


@pytest.mark.parametrize("fail_supplement", [False, True])
@pytest.mark.asyncio
async def test_second_mention_cannot_reuse_another_mentions_global_vector_candidate(
    linking_graph, fail_supplement
):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    second = recipe_to_facts("清蒸鲈鱼", {"主食材": [["鲈鱼", "100克"]], "做法": "1:清蒸鲈鱼。"})
    await scope.store.upsert(second)
    page = await scope.store.export_linking_records(limit=100)
    variants = {
        record.label: record for record in page.records if record.object_type == "RecipeVariant"
    }
    batches = []

    class Embeddings:
        def embed_query(self, text):
            batches.append([text])
            return [1.0, 0.0]

        def embed_documents(self, texts):
            batches.append(texts)
            if fail_supplement:
                raise RuntimeError("Isolated candidate provider failure")
            return [[0.0, 1.0] for text in texts]

    class Store:
        def search(self, vector, *, scope, generation_id, **kwargs):
            if scope.kind == "concept":
                return []
            candidate = variants["清蒸鲈鱼" if vector == [0.0, 1.0] else "佛跳墙"]
            return [
                CandidateHit(
                    record=candidate,
                    scope=scope,
                    generation_id=generation_id,
                    vector_score=0.95,
                )
            ]

    def publication(index_scope):
        return IndexPublicationStatus(
            scope=index_scope,
            generation_id="two_mentions",
            status="ready",
            graph_revision=2 if index_scope.kind == "entity" else None,
            calibration_id="fixture",
            policy={"min_cosine": 0.8, "margin": 0.05},
        )

    index_scopes: dict[str, IndexScope] = {
        kind: IndexScope(
            domain_id=scope.domain.id,
            ontology_version=scope.domain.version,
            ontology_fingerprint=scope.domain.semantic_model.fingerprint,
            embedding_fingerprint="b" * 64,
            kind=kind,
        )
        for kind in CANDIDATE_KINDS
    }
    linker = EntityLinkingService(
        scope.domain,
        graph_store=scope.store,
        candidate_store=Store(),
        embedder=Embeddings(),
        scopes=index_scopes,
        publication_provider=publication,
        mode="on",
    )
    context = await linker.prepare(
        "佛跳墙和清蒸鲈渔怎么做？", history=[], expected_types=["RecipeVariant"]
    )
    references = [
        ObjectReference(mention=mention, expected_type="RecipeVariant")
        for mention in ("佛跳墙", "清蒸鲈渔")
    ]
    await linker.supplement(references, context=context)
    result = await linker.resolve(references, context=context)
    if fail_supplement:
        assert result.status != "resolved"
        assert result.references[1].ref_id is None
    else:
        assert result.status == "resolved"
        assert [reference.ref_id for reference in result.references] == [
            variants["佛跳墙"].ref_id,
            variants["清蒸鲈鱼"].ref_id,
        ]
    assert len(batches) <= 2


@pytest.mark.parametrize("fail_store", [False, True])
@pytest.mark.asyncio
async def test_target_ingredient_uses_the_same_postplan_batch_without_another_model(
    linking_graph, fail_store
):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    records = (await scope.store.export_linking_records(limit=100)).records
    ingredient = next(
        record
        for record in records
        if record.object_type == "Ingredient" and record.label == "鸡肉"
    )
    batches = []

    class Embeddings:
        def embed_query(self, text):
            batches.append([text])
            return [1.0, 0.0]

        def embed_documents(self, texts):
            batches.append(list(texts))
            return [[1.0, 0.0] for _ in texts]

    class Store:
        def search(self, vector, *, scope, generation_id, expected_types, **kwargs):
            if fail_store:
                raise RuntimeError("Isolated optional ANN outage")
            return (
                [
                    CandidateHit(
                        record=ingredient,
                        scope=scope,
                        generation_id=generation_id,
                        vector_score=0.95,
                    )
                ]
                if scope.kind == "entity" and "Ingredient" in expected_types
                else []
            )

    scopes: dict[str, IndexScope] = {
        kind: IndexScope(
            domain_id=scope.domain.id,
            ontology_version=scope.domain.version,
            ontology_fingerprint=scope.domain.semantic_model.fingerprint,
            embedding_fingerprint="b" * 64,
            kind=kind,
        )
        for kind in CANDIDATE_KINDS
    }

    def publication(index_scope):
        return IndexPublicationStatus(
            scope=index_scope,
            generation_id="ingredient-index",
            status="ready",
            graph_revision=1 if index_scope.kind == "entity" else None,
            calibration_id="protocol-fixture",
            policy={"min_cosine": 0.8, "margin": 0.05},
        )

    linker = EntityLinkingService(
        scope.domain,
        graph_store=scope.store,
        candidate_store=Store(),
        embedder=Embeddings(),
        scopes=scopes,
        publication_provider=publication,
        mode="on",
    )

    class Planner:
        def __init__(self):
            self.calls = 0

        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            return {
                "facts": True,
                "entity_type": "RecipeVariant",
                "entity_mentions": ["佛跳墙"],
                "requests": [{"property": "ingredientQuantity", "target": "鸡内"}],
            }

    planner = Planner()
    question = "佛跳墙加多少鸡内？" if fail_store else "请问佛跳墙中鸡内的用量"
    answer = await KnowledgeQueryService(
        scope.domain, graph_store=scope.store, documents=None, model=planner, linker=linker
    ).answer(question)
    if fail_store:
        assert answer.metadata["status"] == "retrieval_unavailable"
        assert "未记录" not in answer.message
        return
    assert "100" in answer.message
    assert planner.calls == 1
    assert batches[-1] == ["鸡内"]
    assert len(batches) <= 2
    assert answer.metadata["bound_targets"]["鸡内"]["ref_id"] == ingredient.ref_id


@pytest.mark.asyncio
async def test_fuzzy_named_count_uses_full_name_family_scope_instead_of_ann_top_one(linking_graph):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    await scope.store.upsert(scope.slow)
    record = next(
        item
        for item in (await scope.store.export_linking_records(limit=100)).records
        if item.object_type == "RecipeVariant"
    )

    class Embeddings:
        def embed_query(self, text):
            return [1.0, 0.0]

        def embed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

    class Store:
        def search(self, vector, *, scope, generation_id, expected_types, **kwargs):
            return (
                []
                if scope.kind == "concept"
                else [
                    CandidateHit(
                        record=record, scope=scope, generation_id=generation_id, vector_score=0.95
                    )
                ]
            )

    scopes: dict[str, IndexScope] = {
        kind: IndexScope(
            domain_id=scope.domain.id,
            ontology_version=scope.domain.version,
            ontology_fingerprint=scope.domain.semantic_model.fingerprint,
            embedding_fingerprint="b" * 64,
            kind=kind,
        )
        for kind in CANDIDATE_KINDS
    }

    def publication(index_scope):
        return IndexPublicationStatus(
            scope=index_scope,
            generation_id="count-index",
            status="ready",
            graph_revision=2 if index_scope.kind == "entity" else None,
            calibration_id="protocol-fixture",
            policy={"min_cosine": 0.8, "margin": 0.05},
        )

    linker = EntityLinkingService(
        scope.domain,
        graph_store=scope.store,
        candidate_store=Store(),
        embedder=Embeddings(),
        scopes=scopes,
        publication_provider=publication,
        mode="on",
    )

    class Planner:
        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            return {
                "facts": True,
                "operation": "count",
                "selection": "all",
                "entity_type": "RecipeVariant",
                "entity_mentions": ["佛挑墙"],
            }

    prepared = await KnowledgeQueryService(
        scope.domain, graph_store=scope.store, documents=None, model=Planner(), linker=linker
    ).prepare("佛挑墙一共有多少份做法版本？")
    assert prepared.facts.total == 2
    assert prepared.plan.anchor_ids == []
    assert prepared.plan.entity_mentions == ["佛跳墙"]


@pytest.mark.asyncio
async def test_planner_ref_id_cannot_override_an_exact_history_mention(linking_graph):
    from langchain_core.messages import HumanMessage

    scope = linking_graph
    await scope.store.upsert(scope.quick)
    other = recipe_to_facts("清蒸鲈鱼", {"主食材": [["鲈鱼", "100克"]], "做法": "1:清蒸鲈鱼。"})
    await scope.store.upsert(other)
    page = await scope.store.export_linking_records(limit=100)
    first = next(
        item
        for item in page.records
        if item.object_type == "RecipeVariant" and item.label == "佛跳墙"
    )
    expected = next(
        item.ref_id
        for item in page.records
        if item.object_type == "RecipeVariant" and item.label == "清蒸鲈鱼"
    )

    class Embeddings:
        def embed_query(self, text):
            return [1.0, 0.0]

        def embed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

    class Store:
        def search(self, vector, *, scope, generation_id, **kwargs):
            return (
                []
                if scope.kind == "concept"
                else [
                    CandidateHit(
                        record=first, scope=scope, generation_id=generation_id, vector_score=0.95
                    )
                ]
            )

    scopes: dict[str, IndexScope] = {
        kind: IndexScope(
            domain_id=scope.domain.id,
            ontology_version=scope.domain.version,
            ontology_fingerprint=scope.domain.semantic_model.fingerprint,
            embedding_fingerprint="b" * 64,
            kind=kind,
        )
        for kind in CANDIDATE_KINDS
    }

    def publication(index_scope):
        return IndexPublicationStatus(
            scope=index_scope,
            generation_id="history-index",
            status="ready",
            graph_revision=2 if index_scope.kind == "entity" else None,
            calibration_id="fixture",
            policy={"min_cosine": 0.8, "margin": 0.05},
        )

    linker = EntityLinkingService(
        scope.domain,
        graph_store=scope.store,
        candidate_store=Store(),
        embedder=Embeddings(),
        scopes=scopes,
        publication_provider=publication,
        mode="on",
    )

    class Planner:
        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            return {
                "facts": True,
                "entity_type": "RecipeVariant",
                "entity_mentions": ["清蒸鲈鱼"],
                "anchor_ids": [first.ref_id],
                "requests": [{"property": "steps"}],
            }

    answer = await KnowledgeQueryService(
        scope.domain, graph_store=scope.store, documents=None, model=Planner(), linker=linker
    ).prepare("它怎么做？", history=[HumanMessage(content="我正在看清蒸鲈鱼")])
    assert answer.status in {
        "needs_clarification",
        "retrieval_unavailable",
    } or answer.plan.anchor_ids == [expected]
    assert answer.plan.anchor_ids != [first.ref_id]
