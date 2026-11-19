"""Recall proposes candidates; authority and name families decide identities."""

import importlib
import importlib.util
from types import SimpleNamespace

import pytest

from gustobot.domain.linking import (
    CandidateHit,
    CandidateKind,
    CatalogRecord,
    GraphRevision,
    IndexPublicationStatus,
    IndexScope,
    LinkedCandidate,
    NameFamilyResult,
    ObjectReference,
)

CANDIDATE_KINDS: tuple[CandidateKind, CandidateKind] = ("concept", "entity")


def record(ref_id="recipe-a", label="家庭版佛跳墙", kind="entity", **fields):
    return CatalogRecord.create(
        domain_id="recipes",
        ontology_version="v3",
        ontology_fingerprint="a" * 64,
        kind=kind,
        ref_kind="entity" if kind == "entity" else "property",
        ref_id=ref_id,
        object_type="RecipeVariant",
        label=label,
        graph_revision=1 if kind == "entity" else None,
        **fields,
    )


def scopes() -> dict[str, IndexScope]:
    return {
        kind: IndexScope(
            domain_id="recipes",
            ontology_version="v3",
            ontology_fingerprint="a" * 64,
            embedding_fingerprint="b" * 64,
            kind=kind,
        )
        for kind in CANDIDATE_KINDS
    }


class Graph:
    def __init__(self, exact=False, family=False):
        self.exact = exact
        self.family = family

    async def graph_revision(self):
        return GraphRevision(
            domain_id="recipes",
            ontology_version="v3",
            ontology_fingerprint="a" * 64,
            state="ready",
            revision=1,
        )

    async def lexical_candidates(self, question, *, expected_types=(), limit=40):
        return [LinkedCandidate(record=record(), match_sources=["exact"])] if self.exact else []

    async def hydrate_candidates(self, ids):
        return [
            LinkedCandidate(record=record(), match_sources=[]) for key in ids if key == "recipe-a"
        ]

    async def lookup_name_family(self, candidate_ids, limit=20):
        items = [LinkedCandidate(record=record(), match_sources=["family"])]
        if self.family:
            items.append(LinkedCandidate(record=record("recipe-b"), match_sources=["family"]))
        return NameFamilyResult(items=items, has_more=False)


class Embedder:
    def __init__(self):
        self.calls = []

    def embed_query(self, text):
        self.calls.append(text)
        return [1.0, 0.0]


class Store:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def search(self, vector, *, scope, generation_id, expected_types, top_k):
        self.calls.append(scope.kind)
        if self.fail:
            raise RuntimeError("candidate provider unavailable")
        if scope.kind == "concept":
            return []
        return [
            CandidateHit(
                record=record(), scope=scope, generation_id=generation_id, vector_score=0.95
            )
        ]


def linker(graph=None, store=None, embedder=None, mode="on", publication=None):
    assert (
        importlib.util.find_spec("gustobot.application.services.entity_linking") is not None
    ), "Entity linking service not implemented"
    module = importlib.import_module("gustobot.application.services.entity_linking")
    domain = SimpleNamespace(
        id="recipes",
        version="v3",
        semantic_model=SimpleNamespace(
            linking_records=lambda: [record("property:steps", "做法", "concept")]
        ),
    )

    def published(scope):
        return IndexPublicationStatus(
            scope=scope,
            generation_id="generation-a",
            graph_revision=1 if scope.kind == "entity" else None,
            status="ready",
            calibration_id="calibration-a",
            policy={"min_cosine": 0.8, "margin": 0.05},
        )

    return module.EntityLinkingService(
        domain,
        graph_store=graph or Graph(),
        candidate_store=store or Store(),
        embedder=embedder or Embedder(),
        scopes=scopes(),
        publication_provider=publication or published,
        mode=mode,
    )


@pytest.mark.asyncio
async def test_exact_name_never_calls_embedding_and_expands_authoritative_family():
    embeddings = Embedder()
    service = linker(Graph(exact=True, family=True), embedder=embeddings)
    context = await service.prepare(
        "家庭版佛跳墙怎么做", history=[], expected_types=["RecipeVariant"]
    )
    result = await service.resolve(
        [ObjectReference(mention="家庭版佛跳墙", expected_type="RecipeVariant")], context=context
    )
    assert result.status == "clarify"
    assert {item.record.ref_id for item in result.candidates} == {"recipe-a", "recipe-b"}
    assert not embeddings.calls


@pytest.mark.asyncio
async def test_one_query_embedding_is_shared_by_concept_and_entity_recall():
    embeddings, store = Embedder(), Store()
    context = await linker(store=store, embedder=embeddings).prepare(
        "家停佛跳墙如何制作", history=[], expected_types=["RecipeVariant"]
    )
    assert len(embeddings.calls) == 1
    assert {item.record.ref_id for item in context.entities} == {"recipe-a"}
    assert len(store.calls) == 2 and set(store.calls) == {"concept", "entity"}
    assert context.provider_calls["candidate_embedding_batches"] == 1


@pytest.mark.asyncio
async def test_vector_top_one_cannot_hide_a_second_real_name_family_member():
    service = linker(Graph(family=True))
    context = await service.prepare("家停佛跳墙做法", history=[], expected_types=["RecipeVariant"])
    result = await service.resolve(
        [ObjectReference(mention="家停佛跳墙", expected_type="RecipeVariant", ref_id="recipe-a")],
        context=context,
    )
    assert result.status == "clarify"
    assert len(result.candidates) == 2


@pytest.mark.asyncio
async def test_stale_generation_is_not_used_and_is_not_reported_as_missing_fact():
    def stale(scope):
        return IndexPublicationStatus(
            scope=scope, generation_id="old", graph_revision=0, status="ready"
        )

    store = Store()
    context = await linker(store=store, publication=stale).prepare(
        "模糊菜名", history=[], expected_types=["RecipeVariant"]
    )
    assert context.status in {"stale", "degraded", "unavailable"}
    assert "entity" not in store.calls


@pytest.mark.asyncio
async def test_provider_failure_is_visible_and_shadow_never_changes_selected_entities():
    context = await linker(store=Store(fail=True)).prepare(
        "模糊菜名", history=[], expected_types=["RecipeVariant"]
    )
    assert context.status == "unavailable" and context.diagnostics
    shadow = await linker(mode="shadow").prepare(
        "模糊菜名", history=[], expected_types=["RecipeVariant"]
    )
    assert shadow.mode == "shadow" and not shadow.entities


@pytest.mark.asyncio
async def test_unrelated_mention_never_receives_all_recalled_candidates():
    service = linker()
    context = await service.prepare("家停佛跳墙做法", history=[], expected_types=["RecipeVariant"])
    result = await service.resolve(
        [ObjectReference(mention="完全无关的菜", expected_type="RecipeVariant")], context=context
    )
    assert result.status == "no_candidates"
    assert result.candidates == []


@pytest.mark.asyncio
async def test_unrelated_truncated_family_does_not_change_a_unique_reference():
    from gustobot.domain.linking import LinkingContext

    item = LinkedCandidate(record=record("recipe-a", "蒸鱼"), match_sources=["exact"])
    other = LinkedCandidate(record=record("recipe-b", "佛跳墙"), match_sources=["family"])
    context = LinkingContext(
        question="蒸鱼怎么做",
        mode="on",
        entities=[item],
        families=[NameFamilyResult(items=[other], has_more=True)],
    )
    result = await linker().resolve(
        [ObjectReference(mention="蒸鱼", expected_type="RecipeVariant")], context=context
    )
    assert result.status == "resolved"
    assert result.references[0].ref_id == "recipe-a"


@pytest.mark.asyncio
async def test_shadow_preserves_concept_selection_as_well_as_entities():
    class ConceptStore(Store):
        def search(self, vector, *, scope, generation_id, expected_types, top_k):
            if scope.kind == "concept":
                return [
                    CandidateHit(
                        record=record("property:steps", "做法", "concept"),
                        scope=scope,
                        generation_id=generation_id,
                        vector_score=0.95,
                    )
                ]
            return super().search(
                vector,
                scope=scope,
                generation_id=generation_id,
                expected_types=expected_types,
                top_k=top_k,
            )

    context = await linker(store=ConceptStore(), mode="shadow").prepare(
        "家停佛跳墙如何烹饪", history=[], expected_types=["RecipeVariant"]
    )
    assert context.concepts == []
    assert context.entities == []


@pytest.mark.asyncio
async def test_graph_revision_race_relinks_once_with_cached_embedding():
    class RacingGraph(Graph):
        def __init__(self):
            super().__init__()
            self.lexical_calls = 0
            self.revision_calls = 0

        async def lexical_candidates(self, question, *, expected_types=(), limit=40):
            self.lexical_calls += 1
            return []

        async def graph_revision(self):
            self.revision_calls += 1
            return GraphRevision(
                domain_id="recipes",
                ontology_version="v3",
                ontology_fingerprint="a" * 64,
                state="ready",
                revision=1 if self.revision_calls == 1 else 2,
            )

    graph, embedder = RacingGraph(), Embedder()
    context = await linker(graph=graph, embedder=embedder).prepare(
        "家停佛跳墙", history=[], expected_types=["RecipeVariant"]
    )
    assert graph.lexical_calls == 2
    assert len(embedder.calls) == 1
    assert context.status in {"stale", "unavailable", "degraded"}


@pytest.mark.asyncio
async def test_rrf_combines_lexical_and_vector_evidence_without_probability_claim():
    class LexicalGraph(Graph):
        async def lexical_candidates(self, question, *, expected_types=(), limit=40):
            return [LinkedCandidate(record=record(), match_sources=["fulltext"])]

    context = await linker(graph=LexicalGraph()).prepare(
        "家停佛跳墙", history=[], expected_types=["RecipeVariant"]
    )
    assert set(context.entities[0].match_sources) >= {"fulltext", "vector"}
    assert context.entities[0].rank_score == pytest.approx(2 / 61)
    assert context.entities[0].vector_score == 0.95


@pytest.mark.asyncio
async def test_candidate_id_cannot_authenticate_an_unrelated_mention():
    service = linker()
    context = await service.prepare("家停佛跳墙做法", history=[], expected_types=["RecipeVariant"])
    result = await service.resolve(
        [ObjectReference(mention="完全无关的菜", expected_type="RecipeVariant", ref_id="recipe-a")],
        context=context,
    )
    assert result.status == "no_candidates"
    assert result.candidates == []


@pytest.mark.asyncio
async def test_new_mentions_share_one_postplan_embedding_batch_and_are_not_repeated():
    from gustobot.domain.linking import LinkingContext

    ingredient = CatalogRecord.create(
        domain_id="recipes",
        ontology_version="v3",
        ontology_fingerprint="a" * 64,
        kind="entity",
        ref_kind="entity",
        ref_id="sugar-id",
        object_type="Ingredient",
        label="白糖",
        graph_revision=1,
    )

    class IngredientGraph(Graph):
        async def hydrate_candidates(self, ids):
            return [LinkedCandidate(record=ingredient)] if "sugar-id" in ids else []

        async def lookup_name_family(self, candidate_ids, limit=20):
            return NameFamilyResult(items=[LinkedCandidate(record=ingredient)])

    class IngredientStore(Store):
        def search(self, vector, *, scope, generation_id, **kwargs):
            return (
                []
                if scope.kind == "concept"
                else [
                    CandidateHit(
                        record=ingredient,
                        scope=scope,
                        generation_id=generation_id,
                        vector_score=0.95,
                    )
                ]
            )

    class BatchEmbedder(Embedder):
        def __init__(self):
            super().__init__()
            self.batches = []

        def embed_documents(self, texts):
            self.batches.append(list(texts))
            return [[1.0, 0.0] for _ in texts]

    embedder = BatchEmbedder()
    service = linker(graph=IngredientGraph(), store=IngredientStore(), embedder=embedder)
    context = LinkingContext(
        question="佛跳墙白糖用量",
        mode="on",
        entities=[LinkedCandidate(record=record())],
        provider_calls={"candidate_embedding_batches": 1},
    )
    references = [ObjectReference(mention="白糖", expected_type="Ingredient")]
    await service.supplement(references, context=context)
    await service.supplement(references, context=context)
    resolution = await service.resolve(references, context=context)
    assert embedder.batches == [["白糖"]]
    assert context.provider_calls["candidate_embedding_batches"] == 2
    assert resolution.references[0].ref_id == "sugar-id"


@pytest.mark.asyncio
async def test_postplan_candidate_deadline_includes_graph_lookup_and_preserves_cancellation():
    import asyncio

    from gustobot.domain.linking import LinkingContext

    entered, cancelled = asyncio.Event(), asyncio.Event()

    class BlockedGraph(Graph):
        async def lexical_candidates(self, question, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    service = linker(graph=BlockedGraph())
    service.deadline = 0.02
    context = LinkingContext(question="佛跳墙的白糖用量", mode="on")
    await asyncio.wait_for(
        service.supplement(
            [ObjectReference(mention="白糖", expected_type="Ingredient")], context=context
        ),
        timeout=0.2,
    )
    assert entered.is_set() and cancelled.is_set()
    assert context.status == "unavailable"
    assert context.entities == []


@pytest.mark.asyncio
async def test_authority_cap_uses_candidate_scores_across_all_expected_types():
    from gustobot.domain.linking import ENTITY_CATALOG_TYPES

    items = {
        kind: [
            CatalogRecord.create(
                domain_id="recipes",
                ontology_version="v3",
                ontology_fingerprint="a" * 64,
                kind="entity",
                ref_kind="entity",
                ref_id=f"{kind}-{index}",
                object_type=kind,
                label=f"{kind}{index}",
                graph_revision=1,
            )
            for index in range(10)
        ]
        for kind in ENTITY_CATALOG_TYPES
    }
    records = {item.ref_id: item for group in items.values() for item in group}

    class TypedStore(Store):
        def search(self, vector, *, scope, generation_id, expected_types, top_k):
            return (
                []
                if scope.kind == "concept"
                else [
                    CandidateHit(
                        record=item,
                        scope=scope,
                        generation_id=generation_id,
                        vector_score=0.99 if item.object_type == "Flavor" else 0.81,
                    )
                    for item in items[expected_types[0]]
                ]
            )

    class TypedGraph(Graph):
        def __init__(self):
            super().__init__()
            self.hydrated = []

        async def hydrate_candidates(self, ids):
            self.hydrated = list(ids)
            return [LinkedCandidate(record=records[key]) for key in sorted(ids)]

        async def lookup_name_family(self, candidate_ids, limit=20):
            return NameFamilyResult(
                items=[LinkedCandidate(record=records[key]) for key in candidate_ids]
            )

    graph = TypedGraph()
    context = await linker(graph=graph, store=TypedStore()).prepare("模糊口味", history=[])
    assert len(graph.hydrated) == 40
    assert {item.ref_id for item in items["Flavor"]} <= set(graph.hydrated)
    assert context.entities[0].record.object_type == "Flavor"


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_scope", [False, True])
async def test_recall_rejects_wrong_scope_or_generation_before_hydration(wrong_scope):
    class UntrustedStore(Store):
        def search(self, vector, *, scope, generation_id, expected_types, top_k):
            if scope.kind == "concept":
                return []
            if wrong_scope:
                scope = scope.model_copy(update={"embedding_fingerprint": "c" * 64})
            else:
                generation_id = "another-generation"
            return [
                CandidateHit(
                    record=record(), scope=scope, generation_id=generation_id, vector_score=0.95
                )
            ]

    class UnusedHydration(Graph):
        async def hydrate_candidates(self, ids):
            raise AssertionError("Out-of-scope recall must not reach graph hydration")

    service = linker(graph=UnusedHydration(), store=UntrustedStore())
    with pytest.raises(ValueError, match="out-of-scope"):
        await service.prepare("家停佛跳墙", history=[], expected_types=["RecipeVariant"])


@pytest.mark.asyncio
async def test_stale_hydrated_content_is_rejected_with_an_explicit_diagnostic():
    class ChangedGraph(Graph):
        async def hydrate_candidates(self, ids):
            return [LinkedCandidate(record=record(label="更新后的佛跳墙"))]

    context = await linker(graph=ChangedGraph()).prepare(
        "家停佛跳墙", history=[], expected_types=["RecipeVariant"]
    )
    assert context.status == "no_candidates" and context.entities == []
    assert "Rejected stale candidate content" in context.diagnostics
