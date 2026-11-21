"""One ontology-driven plan combines fact and document evidence."""

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from gustobot.config.domain import get_domain_definition
from gustobot.domain.knowledge import (
    EvidenceReference,
    KnowledgeEntity,
    KnowledgeRelation,
    SourceDocument,
)
from gustobot.infrastructure.knowledge.graph_store import EntityCandidate, FactResult


def test_formal_planner_boundary_rejects_native_routing_and_accepts_composable_properties():
    from gustobot.application.services.knowledge_query import SemanticQuestionPlan

    schema = SemanticQuestionPlan
    plan = schema.model_validate(
        {
            "facts": True,
            "requests": [
                {"property": "ingredientQuantity", "target": "糖"},
                {"property": "reportedTime"},
            ],
        }
    )
    assert [item.property for item in plan.requests] == [
        "ingredientQuantity",
        "reportedTime",
    ]
    for native in (
        {"fields": ["RecipeVariant.cook_time"]},
        {"relation_types": ["HAS_AUX_INGREDIENT"]},
        {"target_names": ["糖"]},
    ):
        with pytest.raises(ValueError):
            schema.model_validate(native)


@pytest.mark.parametrize("kind", ["semantic", "native"])
def test_planning_prompts_limit_attributes_to_the_request_and_combine_article_needs(kind):
    service = query_service()
    prompt = (
        service._semantic_prompt()
        if kind == "semantic"
        else service._native_prompt("说明操作步骤，并结合相关文章补充技巧", [])
    ).split("\n", 1)[0]
    assert "仅包含用户明确请求的属性" in prompt
    assert "不能为了全面介绍而枚举目录" in prompt
    assert "步骤或过程不自动追加数值用量、时长或其他属性" in prompt
    assert "文章、背景、技巧或解释需求时必须设置 documents=true" in prompt
    assert "可与 facts=true 组合" in prompt


class Graph:
    def __init__(self, ambiguous=False, empty=False):
        self.queries = []
        self.ambiguous = ambiguous
        self.empty = empty
        self.domain = get_domain_definition()

    async def resolve_entities(self, name, entity_types=None, limit=10):
        count = 2 if self.ambiguous else 1
        return [
            EntityCandidate(
                id=f"recipe-{i}",
                type="RecipeVariant",
                name=f"佛跳墙做法{i}",
                aliases=["佛跳墙"],
            )
            for i in range(count)
        ]

    async def query(self, request):
        self.queries.append(request)
        if self.empty:
            return FactResult(
                entities=[],
                relations=[],
                sources=[],
                total=0,
                truncated=False,
                ontology_version=self.domain.version,
            )
        evidence = [EvidenceReference(source_id="manual", quote="佛跳墙的糖用量为适量。")]
        anchor_id = request.anchor_ids[0] if request.anchor_ids else "recipe-0"
        return FactResult(
            entities=[
                KnowledgeEntity(
                    id=anchor_id,
                    type="RecipeVariant",
                    name="佛跳墙做法0",
                    aliases=["佛跳墙"],
                    properties={"source_record_id": "controlled-record"},
                    evidence=evidence,
                ),
                KnowledgeEntity(id="sugar", type="Ingredient", name="糖", evidence=evidence),
            ],
            relations=[
                KnowledgeRelation(
                    id="uses-sugar",
                    source_id=anchor_id,
                    target_id="sugar",
                    type="HAS_AUX_INGREDIENT",
                    properties={"amount_text": "适量"},
                    evidence=evidence,
                )
            ],
            sources=[SourceDocument(id="manual", text=evidence[0].quote, uri="recipe-source.txt")],
            total=1,
            truncated=False,
            ontology_version=self.domain.version,
        )


class Documents:
    def __init__(self):
        self.queries = []
        self.scopes = []

    async def search(self, query, **kwargs):
        self.queries.append(query)
        self.scopes.append(kwargs)
        return [
            {
                "id": "chunk-1",
                "content": "原文记载了这道菜的来历。",
                "score": 0.9,
                "metadata": {
                    "source_id": "history",
                    "uri": "history.txt",
                    "source_version": "v1",
                    "domain_id": "recipes",
                },
            }
        ]


class Model:
    def __init__(self, plan):
        self.plan = plan
        self.analysis = []
        self.generations = []

    def with_structured_output(self, schema, **kwargs):
        model = self

        class Planner:
            async def ainvoke(self, messages):
                model.analysis.append(messages)
                return model.plan

        return Planner()

    async def ainvoke(self, messages):
        self.generations.append(messages)
        return AIMessage(content="依据当前做法和原文：糖为适量，来历见来源。")

    async def astream(self, messages):
        self.generations.append(messages)
        yield AIMessage(content="依据当前做法，")
        yield AIMessage(content="糖为适量。")


def selected_material():
    from gustobot.application.services.knowledge_query import SelectedKnowledgeContext

    source = SourceDocument(
        id="selected-a",
        text='{"name":"家庭版佛跳墙","ingredients":[{"name":"糖","amount":"2克"}]}',
        uri="https://example.org/current-source",
    )
    facts = FactResult(
        entities=[
            KnowledgeEntity(
                id="dish-0",
                type="Dish",
                name="佛跳墙",
                evidence=[
                    EvidenceReference(source_id="article-graph", quote="佛跳墙属于菜品概念。")
                ],
            )
        ],
        relations=[],
        sources=[
            SourceDocument(
                id="article-graph",
                text="佛跳墙属于菜品概念。",
                uri="https://example.org/background",
            )
        ],
        total=1,
        truncated=False,
        ontology_version=get_domain_definition().version,
    )
    return SelectedKnowledgeContext(
        source=source,
        citation={
            "backend": "selected-document",
            "source": "家庭版佛跳墙",
            "url": source.uri,
            "source_version": "a" * 64,
        },
        document_query="佛跳墙的做法和来历",
        related_entity_ids=["dish-0"],
        facts=facts,
        parameters={"requested_servings": 3},
    )


@pytest.mark.asyncio
async def test_selected_context_combines_current_source_concept_facts_and_articles_once():
    import json

    def forbidden_graph():
        raise AssertionError("The caller has already resolved exact selected graph evidence")

    model, documents, context = Model({}), Documents(), selected_material()
    service = query_service(graph=forbidden_graph, model=model, documents=documents)
    result = await service.answer_selected(
        "原方用量及这道菜的来历？", context, history=[HumanMessage(content="我正在读家庭版。")]
    )
    assert not model.analysis and len(model.generations) == 1
    assert documents.scopes[0]["entity_ids"] == ["dish-0"]
    assert documents.queries == [context.document_query]
    assert {source["backend"] for source in result.sources} == {
        "selected-document",
        "neo4j",
        "milvus",
    }
    payload = json.loads(model.generations[0][-1].content.split("\n本轮证据：\n", 1)[1])
    assert payload["selected_source"]["source"]["text"] == context.source.text
    assert payload["selected_source"]["parameters"] == {"requested_servings": 3}
    assert payload["facts_scope"] == "related-concepts"
    assert payload["facts"]["entities"][0]["type"] == "Dish"
    assert "当前选中原文" in model.generations[0][0].content
    assert "我正在读家庭版。" in str(model.generations[0])
    assert result.sources[0]["source_version"] == "a" * 64
    assert result.metadata["generation_calls"] == 1


@pytest.mark.asyncio
async def test_selected_scaling_parameters_preserve_original_values_and_require_a_reliable_basis():
    import json

    context, model = selected_material(), Model({})
    await query_service(model=model).answer_selected("请换算成三份，并说明数量是否可靠", context)
    instructions = model.generations[0][0].content
    payload = json.loads(model.generations[0][-1].content.split("\n本轮证据：\n", 1)[1])
    assert payload["selected_source"]["parameters"] == {"requested_servings": 3}
    original = json.loads(payload["selected_source"]["source"]["text"])
    assert original["ingredients"][0]["amount"] == "2克" and "servings" not in original
    assert "原始基数、数量及单位明确可靠" in instructions
    assert "保留单位并区分原量与计算量" in instructions
    assert "范围、适量和复杂原文不能变成零或精确值" in instructions
    assert "未知属性、功效和数量须明确说明" in instructions


@pytest.mark.asyncio
async def test_article_uncertainty_and_plain_style_rules_reach_the_actual_generation_prompt():
    import json

    class UncertainArticles(Documents):
        async def search(self, *args, **kwargs):
            articles = await super().search(*args, **kwargs)
            articles[0]["content"] = "相传与旧时宴席有关，相关来历仍有争议，尚未核实。"
            return articles

    model = Model({})
    await query_service(model=model, documents=UncertainArticles()).answer_selected(
        "说明原方与文章的不同，并简短介绍来历", selected_material()
    )
    instructions = model.generations[0][0].content
    payload = json.loads(model.generations[0][-1].content.split("\n本轮证据：\n", 1)[1])
    assert payload["documents"][0]["content"] == "相传与旧时宴席有关，相关来历仍有争议，尚未核实。"
    assert "相传、争议、未核实等限定须保留到复述、归纳及结尾" in instructions
    assert "不得将其升级为确定事实或自行宣称来源有权威考证" in instructions
    assert "默认简洁自然，不用 emoji 或装饰性分级" in instructions
    assert "正文不输出内部字段名、对象ID、哈希或空值状态" in instructions


@pytest.mark.asyncio
async def test_selected_context_without_an_exact_graph_mapping_never_invents_graph_sources():
    context, model, documents = selected_material(), Model({}), Documents()
    context.facts = None
    result = await query_service(model=model, documents=documents).answer_selected(
        "解释这份资料", context
    )
    assert {source["backend"] for source in result.sources} == {"selected-document", "milvus"}
    assert documents.scopes[0]["entity_ids"] == ["dish-0"]
    assert "recipe-0" not in str(model.generations)


@pytest.mark.asyncio
async def test_related_concept_evidence_does_not_expose_another_versions_full_source():
    import json

    context, model = selected_material(), Model({})
    assert isinstance(context.facts, FactResult)
    context.facts.sources[0].text = '{"name":"另一版本佛跳墙","sugar":"999克"}'
    await query_service(model=model).answer_selected("解释这份资料", context)
    payload = json.loads(model.generations[0][-1].content.split("\n本轮证据：\n", 1)[1])
    assert "999克" not in str(model.generations)
    assert payload["facts"]["entities"][0]["evidence"][0]["quote"] == "佛跳墙属于菜品概念。"
    assert payload["facts_scope"] == "related-concepts"
    assert payload["selected_source"]["source"]["text"] == context.source.text


@pytest.mark.asyncio
async def test_selected_context_streams_actual_model_chunks_with_all_sources_once():
    import json

    context, model, documents = selected_material(), Model({}), Documents()
    events = [
        event
        async for event in query_service(model=model, documents=documents).stream(
            "说明这份资料", selected=context, history=[HumanMessage(content="正在读这份资料。")]
        )
    ]
    assert [event["content"] for event in events if event["type"] == "message"] == [
        "依据当前做法，",
        "糖为适量。",
    ]
    assert events[-1]["message"] == "依据当前做法，糖为适量。"
    assert {source["backend"] for source in events[-1]["sources"]} == {
        "selected-document",
        "neo4j",
        "milvus",
    }
    assert not model.analysis and len(model.generations) == 1
    assert len(documents.queries) == 1
    assert events[-1]["metadata"]["generation_calls"] == 1
    payload = json.loads(model.generations[0][-1].content.split("\n本轮证据：\n", 1)[1])
    assert payload["selected_source"]["source"]["text"] == context.source.text
    assert "正在读这份资料。" in str(model.generations[0])


@pytest.mark.asyncio
async def test_closing_selected_context_stream_closes_its_model_generator():
    closed = []

    class StreamingModel(Model):
        async def astream(self, messages):
            try:
                yield AIMessage(content="第一段")
                yield AIMessage(content="第二段")
            finally:
                closed.append(True)

    stream = query_service(model=StreamingModel({})).stream(
        "说明这份资料", selected=selected_material()
    )
    assert (await stream.__anext__())["type"] == "metadata"
    assert (await stream.__anext__())["content"] == "第一段"
    await stream.aclose()
    assert closed == [True]


@pytest.mark.asyncio
async def test_selected_context_without_linked_entities_does_not_expand_to_global_documents():
    class UnrelatedDocuments(Documents):
        async def search(self, *args, **kwargs):
            raise AssertionError("An unlinked source must not search the entire corpus")

    context, model = selected_material(), Model({})
    context.related_entity_ids = []
    context.facts = None
    result = await query_service(model=model, documents=UnrelatedDocuments()).answer_selected(
        "解释这份资料", context
    )
    assert result.sources == [context.citation]
    assert result.metadata["evidence_status"]["documents"] == "unlinked"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question, expected",
    [
        ("只依据当前资料：用量是什么？", {"selected-document"}),
        ("只查图谱：这是什么概念？", {"neo4j"}),
        ("只查文档：典故是什么？", {"milvus"}),
    ],
)
async def test_selected_context_honors_an_explicit_evidence_restriction(question, expected):
    import json

    model, documents, context = Model({}), Documents(), selected_material()
    result = await query_service(model=model, documents=documents).answer_selected(
        question, context
    )
    assert {source["backend"] for source in result.sources} == expected
    assert bool(documents.queries) is (expected == {"milvus"})
    payload = json.loads(model.generations[0][-1].content.split("\n本轮证据：\n", 1)[1])
    assert (payload["selected_source"] is not None) is (expected == {"selected-document"})


@pytest.mark.asyncio
async def test_selected_source_only_never_loads_graph_facts():
    async def unavailable_graph():
        raise AssertionError("Source-only answers must not initialize the graph")

    context = selected_material()
    context.facts = unavailable_graph
    result = await query_service(model=Model({})).answer_selected(
        "只看当前原文：用量是什么？", context
    )
    assert result.sources == [context.citation]
    assert result.metadata["evidence_status"]["facts"] == "not_requested"


@pytest.mark.asyncio
async def test_selected_context_loads_facts_once_and_rejects_stale_ontology_before_documents():
    context, documents, model = selected_material(), Documents(), Model({})
    facts = context.facts
    assert isinstance(facts, FactResult)
    facts.ontology_version = "old-version"
    calls = []

    async def load_facts():
        calls.append(1)
        return facts

    context.facts = load_facts
    with pytest.raises(ValueError, match="different ontology version"):
        await query_service(model=model, documents=documents).answer_selected(
            "说明这份资料", context
        )
    assert calls == [1] and not documents.queries and not model.generations


@pytest.mark.asyncio
async def test_selected_context_document_failure_remains_a_failure_before_generation():
    class FailedDocuments(Documents):
        async def search(self, *args, **kwargs):
            raise RuntimeError("article index unavailable")

    model = Model({})
    with pytest.raises(RuntimeError, match="article index unavailable"):
        await query_service(model=model, documents=FailedDocuments()).answer_selected(
            "说明这份资料", selected_material()
        )
    assert not model.generations


@pytest.mark.asyncio
async def test_selected_context_cancellation_is_not_reported_as_missing_articles():
    import asyncio

    class CancelledDocuments(Documents):
        async def search(self, *args, **kwargs):
            raise asyncio.CancelledError

    model = Model({})
    with pytest.raises(asyncio.CancelledError):
        await query_service(model=model, documents=CancelledDocuments()).answer_selected(
            "说明这份资料", selected_material()
        )
    assert not model.generations


@pytest.mark.asyncio
async def test_selected_context_without_a_model_fails_before_loading_evidence():
    async def forbidden_facts():
        raise AssertionError("Do not retrieve evidence without a generator")

    context = selected_material()
    context.facts = forbidden_facts
    with pytest.raises(RuntimeError, match="语言模型"):
        await query_service().answer_selected("说明这份资料", context)


@pytest.mark.asyncio
async def test_selected_graph_only_without_graph_facts_does_not_substitute_original_or_articles():
    context, model, documents = selected_material(), Model({}), Documents()
    context.facts = None
    result = await query_service(model=model, documents=documents).answer_selected(
        "只查图谱：解释这个概念", context
    )
    assert result.metadata["status"] == "no_results"
    assert not result.sources and not documents.queries and not model.generations


@pytest.mark.asyncio
async def test_nonaggregate_fact_question_also_reads_related_documents_when_facts_exist():
    model = Model(
        {
            "facts": True,
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "ingredientQuantity", "target": "糖"}],
        }
    )
    documents = Documents()
    result = await query_service(model=model, documents=documents).answer("想了解佛跳墙糖的用量")
    assert documents.scopes[0]["entity_ids"] == ["recipe-0"]
    assert {source["backend"] for source in result.sources} == {"neo4j", "milvus"}
    assert result.metadata["plan"]["documents"] is True
    assert len(model.generations) == 1


class ConceptGraph(Graph):
    def __init__(
        self,
        *,
        connected=True,
        domain=None,
        anchor_type="RecipeVariant",
        concept_type="Dish",
        relation_type="VARIANT_OF",
    ):
        super().__init__()
        self.connected = connected
        if domain is not None:
            self.domain = domain
        self.anchor_type = anchor_type
        self.concept_type = concept_type
        self.relation_type = relation_type

    async def resolve_entities(self, *args, **kwargs):
        candidates = await super().resolve_entities(*args, **kwargs)
        for candidate in candidates:
            candidate.type = self.anchor_type
        return candidates

    async def query(self, request):
        result = await super().query(request)
        result.entities[0].type = self.anchor_type
        if self.relation_type not in request.relation_types:
            return result
        evidence = [EvidenceReference(source_id="concept-link", quote="当前版本明确归属这一概念。")]
        result.entities.extend(
            [
                KnowledgeEntity(
                    id="dish-0", type=self.concept_type, name="佛跳墙", evidence=evidence
                ),
                KnowledgeEntity(
                    id="another-version",
                    type=self.anchor_type,
                    name="同名其他版本",
                    properties={"cook_time": "999小时"},
                    evidence=evidence,
                ),
            ]
        )
        result.relations = [
            KnowledgeRelation(
                id="unrelated-link",
                source_id="another-version",
                target_id="dish-0",
                type=self.relation_type,
                evidence=evidence,
            ),
        ]
        if self.connected:
            result.relations.append(
                KnowledgeRelation(
                    id="concept-link",
                    source_id="recipe-0",
                    target_id="dish-0",
                    type=self.relation_type,
                    evidence=evidence,
                )
            )
        result.sources.append(
            SourceDocument(
                id="concept-link", text="同名其他版本的用量为999克。当前版本明确归属这一概念。"
            )
        )
        return result


class EntityScopedArticles(Documents):
    async def search(self, query, **kwargs):
        articles = await super().search(query, **kwargs)
        for article in articles:
            article["metadata"]["entity_ids"] = ["dish-0"]
        return [
            article
            for article in articles
            if set(article["metadata"]["entity_ids"]).intersection(kwargs["entity_ids"])
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("connected", [True, False])
async def test_fact_question_reads_concept_articles_only_through_confirmed_forward_relations(
    connected,
):
    graph, documents = ConceptGraph(connected=connected), EntityScopedArticles()
    model = Model(
        {
            "facts": True,
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "ingredientQuantity", "target": "糖"}],
        }
    )
    answer = await query_service(graph=graph, model=model, documents=documents).answer(
        "想了解佛跳墙糖的用量"
    )
    assert documents.scopes[0]["entity_ids"] == (
        ["recipe-0", "dish-0"] if connected else ["recipe-0"]
    )
    assert {source["backend"] for source in answer.sources} == (
        {"neo4j", "milvus"} if connected else {"neo4j"}
    )
    assert len(model.generations) == int(connected)
    assert "适量" in answer.message
    assert "999" not in str(model.generations)
    assert "VARIANT_OF" not in graph.queries[0].relation_types
    assert graph.queries[1].anchor_ids == ["recipe-0"] and graph.queries[1].max_hops == 1
    assert graph.queries[1].filters == [] and graph.queries[1].operation == "lookup"


@pytest.mark.asyncio
async def test_concept_article_scope_follows_renamed_ontology_bindings_in_another_domain(tmp_path):
    from pathlib import Path

    from gustobot.application.services.knowledge_query import KnowledgeQueryService
    from gustobot.domain.formal_ontology import load_formal_ontology

    ontology_dir = Path(__file__).resolve().parents[1] / "gustobot/config/ontologies"
    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        text = (ontology_dir / name).read_text(encoding="utf-8")
        (tmp_path / name).write_text(
            text.replace("RecipeVariant", "DocumentEdition")
            .replace("Dish", "Topic")
            .replace("VARIANT_OF", "DESCRIBES_TOPIC"),
            encoding="utf-8",
        )
    domain = load_formal_ontology(
        tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl"
    ).domain_definition()
    graph = ConceptGraph(
        domain=domain,
        anchor_type="DocumentEdition",
        concept_type="Topic",
        relation_type="DESCRIBES_TOPIC",
    )
    documents = EntityScopedArticles()
    model = Model(
        {
            "facts": True,
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "ingredientQuantity", "target": "糖"}],
        }
    )
    answer = await KnowledgeQueryService(
        domain, graph_store=graph, documents=documents, model=model
    ).answer("查询这个版本的糖用量")
    assert documents.scopes[0]["entity_ids"] == ["recipe-0", "dish-0"]
    assert {source["backend"] for source in answer.sources} == {"neo4j", "milvus"}
    assert graph.queries[1].entity_type == "DocumentEdition"
    assert "DESCRIBES_TOPIC" in graph.queries[1].relation_types


@pytest.mark.asyncio
async def test_explicit_graph_only_fact_question_does_not_automatically_add_articles():
    model = Model(
        {
            "facts": True,
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "ingredientQuantity", "target": "糖"}],
        }
    )
    documents = Documents()
    graph = ConceptGraph()
    result = await query_service(graph=graph, model=model, documents=documents).answer(
        "只查图谱：佛跳墙糖的用量"
    )
    assert not documents.queries and not model.generations
    assert {source["backend"] for source in result.sources} == {"neo4j"}
    assert len(graph.queries) == 1 and "VARIANT_OF" not in graph.queries[0].relation_types


@pytest.mark.asyncio
async def test_empty_explicit_graph_only_question_does_not_fall_back_to_articles():
    model = Model(
        {
            "facts": True,
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "ingredientQuantity", "target": "糖"}],
        }
    )
    documents = Documents()
    result = await query_service(graph=Graph(empty=True), model=model, documents=documents).answer(
        "只查图谱：佛跳墙加多少糖？"
    )
    assert result.metadata["status"] == "no_results"
    assert not documents.queries and not model.generations


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.asyncio
async def test_verified_fact_prefix_does_not_hide_empty_article_generation(streaming):
    class EmptyModel(Model):
        async def ainvoke(self, messages):
            return AIMessage(content=" ")

        async def astream(self, messages):
            yield AIMessage(content=" ")

    service = query_service(model=EmptyModel({}))
    with pytest.raises(ValueError, match="returned no text"):
        if streaming:
            _ = [event async for event in service.stream("佛跳墙加多少糖？")]
        else:
            await service.answer("佛跳墙加多少糖？")


def query_service(graph=None, documents=None, model=None):
    from gustobot.application.services.knowledge_query import KnowledgeQueryService

    return KnowledgeQueryService(
        get_domain_definition(),
        graph_store=Graph() if graph is None else graph,
        documents=Documents() if documents is None else documents,
        model=model,
    )


def semantic_linker_for(graph, *, exact=False, family=False, mode="on"):
    from gustobot.application.services.entity_linking import EntityLinkingService
    from gustobot.domain.linking import (
        CandidateHit,
        CandidateKind,
        CatalogRecord,
        GraphRevision,
        IndexPublicationStatus,
        IndexScope,
        LinkedCandidate,
        NameFamilyResult,
    )

    domain = get_domain_definition()
    formal = domain.semantic_model
    assert formal is not None
    fingerprint = formal.fingerprint

    def record(index=0):
        return CatalogRecord.create(
            domain_id=domain.id,
            ontology_version=domain.version,
            ontology_fingerprint=fingerprint,
            kind="entity",
            ref_kind="entity",
            ref_id=f"recipe-{index}",
            object_type="RecipeVariant",
            label="佛跳墙",
            aliases=[],
            graph_revision=1,
        )

    class IndexGraph:
        async def lexical_candidates(self, question, **kwargs):
            return [LinkedCandidate(record=record(), match_sources=["exact"])] if exact else []

        async def graph_revision(self):
            return GraphRevision(
                domain_id=domain.id,
                ontology_version=domain.version,
                ontology_fingerprint=fingerprint,
                state="ready",
                revision=1,
            )

        async def hydrate_candidates(self, ids):
            return [
                LinkedCandidate(record=record(), match_sources=[])
                for item in ids
                if item == "recipe-0"
            ]

        async def lookup_name_family(self, ids, **kwargs):
            return NameFamilyResult(
                items=[
                    LinkedCandidate(record=record(index), match_sources=["family"])
                    for index in range(2 if family else 1)
                ]
            )

    class Embeddings:
        def __init__(self):
            self.calls = []

        def embed_query(self, question):
            self.calls.append(question)
            return [1.0, 0.0]

    class Store:
        def search(self, vector, *, scope, generation_id, **kwargs):
            return (
                []
                if scope.kind == "concept"
                else [
                    CandidateHit(
                        record=record(), scope=scope, generation_id=generation_id, vector_score=0.95
                    )
                ]
            )

    index_kinds: tuple[CandidateKind, ...] = ("concept", "entity")
    scopes: dict[str, IndexScope] = {
        kind: IndexScope(
            domain_id=domain.id,
            ontology_version=domain.version,
            ontology_fingerprint=fingerprint,
            embedding_fingerprint="b" * 64,
            kind=kind,
        )
        for kind in index_kinds
    }

    def publication(scope):
        return IndexPublicationStatus(
            scope=scope,
            generation_id="index-a",
            graph_revision=1 if scope.kind == "entity" else None,
            status="ready",
            calibration_id="fixed-eval",
            policy={"min_cosine": 0.8, "margin": 0.05},
        )

    embeddings = Embeddings()
    return (
        EntityLinkingService(
            domain,
            graph_store=IndexGraph(),
            candidate_store=Store(),
            embedder=embeddings,
            scopes=scopes,
            publication_provider=publication,
            mode=mode,
        ),
        embeddings,
    )


@pytest.mark.asyncio
async def test_vector_linked_id_enters_the_single_plan_and_fact_execution():
    from gustobot.application.services.knowledge_query import KnowledgeQueryService

    graph = Graph()
    linker, embeddings = semantic_linker_for(graph)
    model = Model(
        {
            "facts": True,
            "entity_type": "RecipeVariant",
            "entity_mentions": ["佛挑墙"],
            "anchor_ids": ["recipe-0"],
            "requests": [{"property": "ingredientQuantity", "target": "糖"}],
        }
    )
    service = KnowledgeQueryService(
        get_domain_definition(),
        graph_store=graph,
        documents=Documents(),
        model=model,
        linker=linker,
    )
    answer = await service.answer("想了解佛挑墙糖的用量")
    assert "recipe-0" in str(model.analysis[0][0].content)
    assert graph.queries[0].anchor_ids == ["recipe-0"]
    assert answer.metadata["model_calls"] == 2
    assert len(model.analysis) == len(model.generations) == 1
    assert answer.metadata["linking"]["selected_ids"] == ["recipe-0"]
    assert len(embeddings.calls) == 1


@pytest.mark.asyncio
async def test_vector_linking_still_clarifies_same_name_family_after_model_selects_top_one():
    from gustobot.application.services.knowledge_query import KnowledgeQueryService

    graph = Graph()
    linker, _ = semantic_linker_for(graph, family=True)
    model = Model(
        {
            "facts": True,
            "entity_type": "RecipeVariant",
            "entity_mentions": ["佛挑墙"],
            "anchor_ids": ["recipe-0"],
            "requests": [{"property": "ingredientQuantity", "target": "糖"}],
        }
    )
    answer = await KnowledgeQueryService(
        get_domain_definition(),
        graph_store=graph,
        documents=Documents(),
        model=model,
        linker=linker,
    ).answer("想了解佛挑墙糖的用量")
    assert answer.metadata["status"] == "needs_clarification"
    assert len(answer.metadata["choices"]) == 2
    assert graph.queries == []


@pytest.mark.asyncio
async def test_explicit_document_only_question_does_not_start_entity_linking():
    from gustobot.application.services.knowledge_query import KnowledgeQueryService

    class Linker:
        mode = "on"

        async def prepare(self, *args, **kwargs):
            raise AssertionError("A document-only request must remain independent of Neo4j")

    def forbidden_graph():
        raise AssertionError("Document-only questions must not initialize graph")

    model = Model({"documents": True})
    answer = await KnowledgeQueryService(
        get_domain_definition(),
        graph_store=forbidden_graph,
        documents=Documents(),
        model=model,
        linker=Linker(),
    ).answer("只查原文：佛跳墙的典故")
    assert answer.sources[0]["backend"] == "milvus"
    assert len(model.analysis) == 1


@pytest.mark.asyncio
async def test_shadow_linking_preserves_the_existing_exact_fast_path():
    from gustobot.application.services.knowledge_query import KnowledgeQueryService

    graph = Graph()
    linker, _ = semantic_linker_for(graph, mode="shadow")
    model = Model(
        {
            "facts": True,
            "entity_type": "RecipeVariant",
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "ingredientQuantity", "target": "糖"}],
        }
    )
    answer = await KnowledgeQueryService(
        get_domain_definition(),
        graph_store=graph,
        documents=Documents(),
        model=model,
        linker=linker,
    ).answer("佛跳墙加多少糖？")
    assert answer.metadata["model_calls"] == 1
    assert not model.analysis and len(model.generations) == 1
    assert answer.metadata["linking"]["mode"] == "shadow"
    assert graph.queries[0].anchor_ids == ["recipe-0"]


@pytest.mark.asyncio
async def test_provider_trace_counts_analysis_and_generation_separately():
    model = Model(
        {
            "facts": True,
            "entity_type": "RecipeVariant",
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "ingredientQuantity", "target": "糖"}],
            "documents": True,
        }
    )
    answer = await query_service(model=model).answer("佛跳墙的糖用量以及这道菜的典故")
    trace = answer.metadata["provider_calls"]
    assert trace["analysis"]["logical_calls"] == 1
    assert trace["generation"]["logical_calls"] == 1
    assert trace["analysis"]["http_attempts"] == 0
    assert "input_tokens" not in trace["analysis"]


@pytest.mark.asyncio
async def test_stream_trace_counts_one_invocation_and_restores_context_between_chunks():
    from gustobot.infrastructure.knowledge.request_telemetry import (
        capture_request_trace,
    )

    model = Model({"documents": True})
    stream = query_service(model=model).stream("原文介绍了什么")
    events = []
    async for event in stream:
        events.append(event)
        with capture_request_trace() as separate:
            assert separate.snapshot() == {}
    trace = events[-1]["metadata"]["provider_calls"]
    assert trace["generation"]["logical_calls"] == 1
    assert trace["analysis"]["logical_calls"] == 1


@pytest.mark.asyncio
async def test_simple_sugar_amount_uses_ontology_relation_and_one_article_generation():
    graph = Graph()
    model = Model({})
    answer = await query_service(graph=graph, model=model).answer("佛跳墙加多少糖？")
    assert "适量" in answer.message
    assert answer.route == "knowledge-query"
    assert answer.metadata["model_calls"] == 1
    assert not model.analysis and len(model.generations) == 1
    assert graph.queries[0].anchor_ids == ["recipe-0"]
    assert graph.queries[0].target_name_groups == []
    assert graph.queries[0].include_anchors is True
    assert "红糖" in graph.queries[0].projections[0].target_names
    assert answer.metadata["plan"]["requests"] == [
        {"property": "ingredientQuantity", "target": "糖", "unit": None, "grain": None}
    ]
    assert "HAS_AUX_INGREDIENT" in graph.queries[0].relation_types
    assert answer.sources[0]["source"] == "recipe-source.txt"


@pytest.mark.asyncio
async def test_unrecorded_sugar_never_becomes_zero_or_an_invented_amount():
    class NoDocuments(Documents):
        async def search(self, query, **kwargs):
            return []

    answer = await query_service(graph=Graph(empty=True), documents=NoDocuments()).answer(
        "佛跳墙加多少糖？"
    )
    assert "未" in answer.message
    assert "0克" not in answer.message and "零克" not in answer.message
    assert answer.metadata["status"] == "no_results"


@pytest.mark.asyncio
async def test_set_lookup_queries_full_database_scope_without_candidate_id_limit():
    class NoNamedAnchor(Graph):
        async def resolve_entities(self, name, entity_types=None, limit=10):
            raise AssertionError("A set query must not enumerate a top-10 candidate sample")

    graph = NoNamedAnchor()
    model = Model(
        {
            "facts": True,
            "selection": "all",
            "entity_type": "RecipeVariant",
            "requests": [{"property": "ingredientQuantity", "target": "糖"}],
            "conditions": [{"property": "ingredientQuantity", "target": "糖"}],
        }
    )
    await query_service(graph=graph, model=model).answer("列出所有使用糖的做法")
    assert graph.queries[0].anchor_ids == []
    names = graph.queries[0].target_name_groups[0]
    assert "糖" in names and "红糖" in names


@pytest.mark.asyncio
async def test_all_versions_of_a_named_dish_use_database_name_scope():
    graph = Graph(ambiguous=True)
    model = Model(
        {
            "facts": True,
            "selection": "all",
            "entity_type": "RecipeVariant",
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "ingredientQuantity"}],
        }
    )
    await query_service(graph=graph, model=model).answer("列出全部佛跳墙做法的辅料")
    assert graph.queries[0].anchor_names == ["佛跳墙"]
    assert graph.queries[0].anchor_ids == []


@pytest.mark.asyncio
async def test_simple_question_can_use_raw_document_without_an_extracted_fact():
    class NoFacts(Graph):
        async def resolve_entities(self, name, entity_types=None, limit=10):
            return []

    model, documents = (
        Model({"documents": True, "document_query": "佛跳墙做法"}),
        Documents(),
    )
    answer = await query_service(graph=NoFacts(), model=model, documents=documents).answer(
        "佛跳墙怎么做？"
    )
    assert len(model.analysis) == 1
    assert len(model.generations) == 1
    assert answer.sources[0]["backend"] == "milvus"
    assert answer.metadata["model_calls"] == 2


@pytest.mark.asyncio
async def test_qualified_name_cannot_bypass_semantic_condition_validation():
    model = Model({"decision": "clarify", "unsupported_conditions": ["30分钟的精确时间比较"]})
    graph = Graph()
    answer = await query_service(graph=graph, model=model).answer("耗时30分钟的佛跳墙加多少糖？")
    assert len(model.analysis) == 1
    assert answer.route == "clarification"
    assert not graph.queries


@pytest.mark.asyncio
async def test_planner_keeps_the_frontends_selected_recipe_context():
    model = Model({"documents": True, "document_query": "家庭版佛跳墙技巧"})
    await query_service(model=model).answer("当前菜谱：家庭版佛跳墙\n\n我的问题：它有哪些技巧？")
    assert "家庭版佛跳墙" in str(model.analysis[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["第2份", "第 2 份"])
async def test_same_name_versions_can_be_selected_by_a_persisted_ordinal(selection):
    class SameNames(Graph):
        async def resolve_entities(self, name, entity_types=None, limit=10):
            candidates = [
                EntityCandidate(
                    id=f"variant-{i}",
                    type="RecipeVariant",
                    name="佛跳墙",
                    source_uris=[f"source-{i}.txt"],
                    summary={"cook_time": f"{i + 1}小时"},
                )
                for i in range(2)
            ]
            explicit = [item for item in candidates if item.id in name]
            return explicit or candidates

    graph = SameNames()
    service = query_service(graph=graph)
    first = await service.answer("佛跳墙加多少糖？")
    assert first.route == "clarification"
    assert "source-0.txt" in first.message and "source-1.txt" in first.message
    previous = AIMessage(
        content=first.message,
        additional_kwargs={
            "knowledge_choices": first.metadata["choices"],
            "knowledge_plan": first.metadata["plan"],
        },
    )
    second = await service.answer(selection, history=[previous])
    assert second.route == "knowledge-query"
    assert graph.queries[0].anchor_ids == ["variant-1"]
    assert second.metadata["model_calls"] == 0


@pytest.mark.asyncio
async def test_partially_missing_requested_properties_are_not_reported_as_complete():
    model = Model(
        {
            "facts": True,
            "entity_type": "RecipeVariant",
            "entity_mentions": ["佛跳墙"],
            "requests": [
                {"property": "ingredientQuantity", "target": "糖"},
                {"property": "reportedTime"},
            ],
        }
    )
    answer = await query_service(model=model).answer("佛跳墙的糖用量及耗时？")
    assert "适量" in answer.message and "未记录" in answer.message
    assert answer.metadata["status"] == "partial"


@pytest.mark.asyncio
async def test_recipe_variants_are_clarified_instead_of_selecting_first_candidate():
    graph = Graph(ambiguous=True)
    answer = await query_service(graph=graph).answer("佛跳墙加多少糖？")
    assert answer.route == "clarification"
    assert "佛跳墙做法0" in answer.message and "佛跳墙做法1" in answer.message
    assert not graph.queries


@pytest.mark.asyncio
async def test_exact_display_name_is_not_a_default_when_other_versions_share_that_alias():
    class NamedVariants(Graph):
        async def resolve_entities(self, name, entity_types=None, limit=10):
            return [
                EntityCandidate(id="recipe-0", type="RecipeVariant", name="佛跳墙", aliases=[]),
                EntityCandidate(
                    id="recipe-1",
                    type="RecipeVariant",
                    name="家庭版佛跳墙",
                    aliases=["佛跳墙"],
                ),
            ]

    graph = NamedVariants()
    answer = await query_service(graph=graph).answer("佛跳墙加多少糖？")
    assert answer.route == "clarification"
    assert not graph.queries


@pytest.mark.asyncio
async def test_full_name_clarifies_only_matching_versions_without_a_shorter_name():
    class OverlappingNames(Graph):
        async def resolve_entities(self, name, entity_types=None, limit=10):
            return [
                EntityCandidate(id="recipe-0", type="RecipeVariant", name="家庭佛跳墙"),
                EntityCandidate(id="recipe-1", type="RecipeVariant", name="家庭佛跳墙"),
                EntityCandidate(id="short-name", type="RecipeVariant", name="佛跳墙"),
            ]

    graph = OverlappingNames()
    answer = await query_service(graph=graph).answer("家庭佛跳墙加多少糖？")
    assert answer.route == "clarification"
    assert {item["id"] for item in answer.metadata["choices"]} == {"recipe-0", "recipe-1"}
    assert not graph.queries


@pytest.mark.asyncio
async def test_history_pronoun_and_mixed_history_question_do_not_bypass_the_plan():
    model = Model(
        {
            "decision": "retrieve",
            "documents": True,
            "document_query": "家庭版佛跳墙的来历",
        }
    )
    documents = Documents()
    await query_service(model=model, documents=documents).answer(
        "它的来历呢？", history=[HumanMessage(content="家庭版佛跳墙")]
    )
    assert len(model.analysis) == 1
    assert documents.queries == ["家庭版佛跳墙的来历"]
    mixed = Model(
        {
            "decision": "retrieve",
            "facts": True,
            "entity_type": "RecipeVariant",
            "requests": [{"property": "steps"}, {"property": "reportedTime"}],
            "anchor_ids": ["recipe-0"],
            "documents": True,
        }
    )
    graph = Graph()
    await query_service(graph=graph, model=mixed).answer("佛跳墙的步骤、耗时及历史")
    assert len(mixed.analysis) == 1
    assert graph.queries


@pytest.mark.asyncio
async def test_document_plan_does_not_discard_structured_conditions():
    model = Model(
        {
            "decision": "retrieve",
            "documents": True,
            "conditions": [{"property": "reportedTime", "op": "eq", "value": "半小时"}],
        }
    )
    documents = Documents()
    answer = await query_service(model=model, documents=documents).answer(
        "找符合时间要求的佛跳墙资料"
    )
    assert answer.route == "clarification"
    assert not documents.queries


@pytest.mark.asyncio
async def test_document_only_plan_does_not_construct_or_query_the_fact_store():
    def unavailable_graph():
        raise AssertionError("Document explanation must not construct Neo4j")

    model = Model({"decision": "retrieve", "documents": True, "document_query": "佛跳墙的来历"})
    answer = await query_service(graph=unavailable_graph, model=model).answer(
        "佛跳墙的来历是什么？"
    )
    assert answer.sources[0]["backend"] == "milvus"


@pytest.mark.asyncio
async def test_named_count_keeps_the_name_scope_in_the_database_query():
    model = Model(
        {
            "decision": "retrieve",
            "facts": True,
            "entity_type": "RecipeVariant",
            "operation": "count",
            "entity_mentions": ["佛跳墙"],
        }
    )
    graph = Graph()
    await query_service(graph=graph, model=model).answer("统计有多少份佛跳墙做法")
    assert graph.queries[0].anchor_names == ["佛跳墙"]
    assert graph.queries[0].operation == "count"


@pytest.mark.asyncio
async def test_resolved_anchor_filters_keep_the_unique_ontology_type():
    model = Model(
        {
            "decision": "retrieve",
            "facts": True,
            "entity_type": "RecipeVariant",
            "requests": [{"property": "reportedTime"}],
            "anchor_ids": ["recipe-0"],
            "conditions": [{"property": "reportedTime", "op": "eq", "value": "半小时"}],
        }
    )
    graph = Graph()
    await query_service(graph=graph, model=model).answer("核对佛跳墙耗时是否记为半小时")
    assert graph.queries[0].entity_type == "RecipeVariant"


@pytest.mark.asyncio
async def test_multi_hop_plan_uses_a_declared_relation_subset_and_bounded_depth():
    model = Model(
        {
            "decision": "retrieve",
            "facts": True,
            "entity_type": "RecipeVariant",
            "anchor_ids": ["recipe-0"],
            "operation": "relations",
            "relation_path": ["HAS_AUX_INGREDIENT", "HAS_NUTRITION_PROFILE"],
            "max_hops": 2,
        }
    )
    graph = Graph()
    await query_service(graph=graph, model=model).answer("查看佛跳墙食材的营养资料关联")
    assert graph.queries[0].max_hops == 2
    assert graph.queries[0].relation_types == [
        "HAS_AUX_INGREDIENT",
        "HAS_NUTRITION_PROFILE",
    ]


@pytest.mark.asyncio
async def test_undefined_semantic_property_is_not_executed():
    model = Model(
        {
            "decision": "retrieve",
            "facts": True,
            "entity_type": "RecipeVariant",
            "anchor_ids": ["recipe-0"],
            "requests": [{"property": "Ingredient.amount_text"}],
        }
    )
    graph = Graph()
    answer = await query_service(graph=graph, model=model).answer("查看当前佛跳墙食材记录")
    assert answer.route == "clarification"
    assert not graph.queries


@pytest.mark.asyncio
async def test_combined_question_uses_one_plan_and_one_generation_with_actual_sources():
    model = Model(
        {
            "decision": "retrieve",
            "facts": True,
            "entity_type": "RecipeVariant",
            "anchor_ids": ["recipe-0"],
            "requests": [{"property": "ingredientQuantity", "target": "糖"}],
            "documents": True,
            "document_query": "佛跳墙的来历",
        }
    )
    documents = Documents()
    answer = await query_service(model=model, documents=documents).answer(
        "给我讲佛跳墙的糖用量和它的来历。",
        history=[HumanMessage(content="我在看家庭版佛跳墙。")],
    )
    assert len(model.analysis) == len(model.generations) == 1
    assert answer.metadata["model_calls"] == 2
    assert {item["backend"] for item in answer.sources} == {"neo4j", "milvus"}
    assert documents.queries == ["佛跳墙的来历"]
    assert documents.scopes[0]["entity_ids"] == ["recipe-0"]
    assert "家庭版佛跳墙" in str(model.analysis[0])
    assert "原文记载" in str(model.generations[0])


@pytest.mark.asyncio
async def test_plan_cannot_invent_anchor_ids_or_drop_unsupported_conditions():
    model = Model(
        {
            "decision": "retrieve",
            "facts": True,
            "entity_type": "RecipeVariant",
            "anchor_ids": ["not-a-candidate"],
            "requests": [{"property": "ingredientQuantity"}],
            "unsupported_conditions": ["无过敏风险"],
        }
    )
    graph = Graph()
    answer = await query_service(model=model, graph=graph).answer("推荐适合特殊要求的佛跳墙。")
    assert answer.route == "clarification"
    assert not graph.queries
    assert not model.generations


@pytest.mark.asyncio
async def test_progress_is_emitted_while_document_retrieval_is_pending(monkeypatch):
    release = asyncio.Event()
    documents = Documents()

    async def delayed_search(*args, **kwargs):
        await release.wait()
        return []

    monkeypatch.setattr(documents, "search", delayed_search)
    service = query_service(model=Model({"documents": True}), documents=documents)
    stream = service.stream("只查原文，菜谱记载了什么？", progress=True)
    try:
        assert await asyncio.wait_for(anext(stream), timeout=2) == {
            "type": "step",
            "name": "planning",
        }
        assert await asyncio.wait_for(anext(stream), timeout=2) == {
            "type": "step",
            "name": "retrieving",
        }
        assert not release.is_set()
        release.set()
        assert await asyncio.wait_for(anext(stream), timeout=2) == {
            "type": "step",
            "name": "answering",
        }
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_stream_yields_real_generation_chunks_and_does_not_regenerate():
    model = Model(
        {
            "decision": "retrieve",
            "facts": True,
            "entity_type": "RecipeVariant",
            "anchor_ids": ["recipe-0"],
            "requests": [{"property": "ingredientQuantity"}],
            "documents": True,
        }
    )
    events = [
        event async for event in query_service(model=model).stream("介绍佛跳墙的做法依据和背景。")
    ]
    messages = [event["content"] for event in events if event["type"] == "message"]
    assert messages[1:] == ["依据当前做法，", "糖为适量。"]
    assert messages[0] == events[-1]["metadata"]["semantic_evaluation"]["message"] + "\n\n"
    assert events[-1]["message"] == "".join(messages)
    assert len(model.analysis) == len(model.generations) == 1
    assert events[-1]["type"] == "done"
    assert events[-1]["metadata"]["model_calls"] == 2


@pytest.mark.asyncio
async def test_closing_response_stream_closes_the_current_model_stream():
    closed = []

    class StreamingModel(Model):
        async def astream(self, messages):
            try:
                yield AIMessage(content="第一段")
                yield AIMessage(content="第二段")
            finally:
                closed.append(True)

    model = StreamingModel({"decision": "retrieve", "documents": True})
    stream = query_service(model=model).stream("请解释这份菜谱资料")
    await stream.__anext__()
    assert (await stream.__anext__())["content"] == "第一段"
    await stream.aclose()
    assert closed == [True]


@pytest.mark.asyncio
async def test_retrieval_failure_cancels_the_other_requested_retrieval():
    import asyncio

    started, closed = asyncio.Event(), []

    class BrokenGraph(Graph):
        async def query(self, request):
            if "VARIANT_OF" in request.relation_types:
                return await super().query(request)
            await started.wait()
            raise RuntimeError("fact store unavailable")

    class WaitingDocuments(Documents):
        async def search(self, query, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.append(True)

    model = Model(
        {
            "decision": "retrieve",
            "facts": True,
            "entity_type": "RecipeVariant",
            "anchor_ids": ["recipe-0"],
            "requests": [{"property": "ingredientQuantity"}],
            "documents": True,
        }
    )
    with pytest.raises(RuntimeError, match="fact store unavailable"):
        await query_service(graph=BrokenGraph(), documents=WaitingDocuments(), model=model).answer(
            "查询佛跳墙食材和文献"
        )
    assert closed == [True]


@pytest.mark.asyncio
async def test_model_cannot_answer_a_recipe_fact_without_retrieving_evidence():
    model = Model({"decision": "answer", "message": "直接放十克糖。"})
    answer = await query_service(model=model).answer("请给我佛跳墙的标准糖用量")
    assert answer.route == "clarification"
    assert "十克" not in answer.message


@pytest.mark.asyncio
async def test_separate_numeric_amount_and_unit_are_displayed_together():
    class UnitsGraph(Graph):
        async def query(self, request):
            result = await super().query(request)
            result.relations[0].properties = {"amount_text": "20", "unit": "g"}
            return result

    answer = await query_service(graph=UnitsGraph()).answer("佛跳墙加多少糖？")
    assert "20 g" in answer.message


@pytest.mark.asyncio
async def test_one_plan_can_project_sugar_amount_and_cooking_time_together():
    class TwoFacts(Graph):
        async def query(self, request):
            result = await super().query(request)
            result.entities[0].properties["cook_time"] = "两小时"
            return result

    model = Model(
        {
            "facts": True,
            "entity_type": "RecipeVariant",
            "entity_mentions": ["佛跳墙"],
            "requests": [
                {"property": "ingredientQuantity", "target": "糖"},
                {"property": "reportedTime"},
            ],
        }
    )
    answer = await query_service(graph=TwoFacts(), model=model).answer(
        "佛跳墙用多少糖、总共需要多久？"
    )
    assert "适量" in answer.message and "两小时" in answer.message
    assert answer.metadata["model_calls"] == 2
    assert len(model.analysis) == len(model.generations) == 1
    assert "capability" not in answer.metadata["plan"]


@pytest.mark.asyncio
async def test_absent_selected_property_does_not_expose_unrequested_properties():
    class MissingTime(Graph):
        async def query(self, request):
            result = await super().query(request)
            result.relations = []
            result.entities = result.entities[:1]
            result.entities[0].properties = {
                "source_record_id": "internal-123",
                "instructions": "另一个未请求的属性",
            }
            return result

    model = Model(
        {
            "facts": True,
            "entity_type": "RecipeVariant",
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "reportedTime"}],
        }
    )
    answer = await query_service(graph=MissingTime(), model=model).answer("佛跳墙耗时多少？")
    assert "internal-123" not in answer.message
    assert "另一个未请求的属性" not in answer.message
    assert "未记录" in answer.message
    assert answer.metadata["status"] == "no_results"


@pytest.mark.asyncio
async def test_missing_quantity_does_not_filter_away_requested_recorded_time():
    class TimeOnly(Graph):
        async def query(self, request):
            result = await super().query(request)
            result.entities = result.entities[:1]
            result.entities[0].properties["cook_time"] = "两小时"
            result.relations = []
            return result

    graph = TimeOnly()
    model = Model(
        {
            "facts": True,
            "entity_mentions": ["佛跳墙"],
            "requests": [
                {"property": "ingredientQuantity", "target": "糖"},
                {"property": "reportedTime"},
            ],
        }
    )
    answer = await query_service(graph=graph, model=model).answer("佛跳墙的糖用量和耗时")
    assert "两小时" in answer.message and "未记录" in answer.message
    assert answer.metadata["status"] == "partial"
    assert graph.queries[0].target_name_groups == []
    assert graph.queries[0].include_anchors is True


@pytest.mark.asyncio
async def test_qualifier_also_requires_planning_when_the_whole_phrase_is_a_stored_alias():
    class QualifiedAlias(Graph):
        async def resolve_entities(self, name, entity_types=None, limit=10):
            return [
                EntityCandidate(
                    id="recipe-0",
                    type="RecipeVariant",
                    name="佛跳墙",
                    aliases=["耗时30分钟的佛跳墙"],
                )
            ]

    graph = QualifiedAlias()
    model = Model({"decision": "clarify", "unsupported_conditions": ["明确时间口径"]})
    answer = await query_service(graph=graph, model=model).answer("耗时30分钟的佛跳墙加多少糖？")
    assert answer.route == "clarification"
    assert len(model.analysis) == 1
    assert not graph.queries


@pytest.mark.asyncio
async def test_superclass_quantity_uses_actual_inference_and_conversion_in_combined_context():
    import json

    class BrownSugar(Graph):
        async def query(self, request):
            result = await super().query(request)
            text = "佛跳墙做法用红糖1000mg，耗时两小时。"
            evidence = [EvidenceReference(source_id="manual", quote=text)]
            for item in [*result.entities, *result.relations]:
                item.evidence = evidence
            result.entities[1].name = "红糖"
            result.relations[0].properties = {"amount_text": "1000", "unit": "mg"}
            result.sources[0].text = text
            return result

    model = Model(
        {
            "facts": True,
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "ingredientQuantity", "target": "糖类", "unit": "g"}],
            "documents": True,
        }
    )
    documents = Documents()
    answer = await query_service(graph=BrownSugar(), model=model, documents=documents).answer(
        "佛跳墙糖类用量换算成克并解释原文"
    )
    context = json.loads(model.generations[0][-1].content.split("\n本轮证据：\n", 1)[1])
    semantic = context["semantic_evaluation"]
    assert semantic["status"] == "success"
    assert "1 g" in semantic["message"] and "红糖" in semantic["message"]
    assert {trace["kind"] for trace in semantic["derivations"]} >= {
        "inferred",
        "converted",
    }
    assert all(trace["premises"] for trace in semantic["derivations"])
    assert context["anchor_ids"] == ["recipe-0"]
    assert context["facts"] is None
    assert documents.scopes[0]["entity_ids"] == ["recipe-0"]
    assert answer.metadata["semantic_evaluation"] == semantic
    assert len(model.analysis) == len(model.generations) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("properties", [{"order": 1}, {"order": 1, "instruction": ""}])
async def test_actual_answer_shape_violation_is_reported_instead_of_native_formatting(
    properties,
):
    class InvalidStep(Graph):
        async def query(self, request):
            result = await super().query(request)
            result.entities[1] = KnowledgeEntity(
                id="step-1",
                type="CookingStep",
                name="第一步",
                properties=properties,
                evidence=result.entities[0].evidence,
            )
            result.relations[0] = KnowledgeRelation(
                id="has-step",
                source_id=result.entities[0].id,
                target_id="step-1",
                type="HAS_STEP",
                properties={"order": 1},
                evidence=result.entities[0].evidence,
            )
            return result

    model = Model({})
    answer = await query_service(graph=InvalidStep(), model=model).answer("佛跳墙怎么做？")
    assert answer.metadata["status"] == "insufficient_evidence"
    assert answer.metadata["semantic_evaluation"]["diagnostics"]
    assert "语义校验" in answer.message
    assert not model.generations


@pytest.mark.asyncio
@pytest.mark.parametrize("operator", ["lte", "eq"])
async def test_uncomparable_time_condition_is_clarified_before_querying(operator):
    graph = Graph()
    model = Model(
        {
            "facts": True,
            "selection": "all",
            "requests": [{"property": "ingredientQuantity"}],
            "conditions": [{"property": "reportedTime", "op": operator, "value": 30}],
        }
    )
    answer = await query_service(graph=graph, model=model).answer("列出耗时不超过30分钟的做法用量")
    assert answer.route == "clarification"
    assert not graph.queries


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requests", "status"),
    [
        ([{"property": "steps"}], "insufficient_evidence"),
        ([{"property": "steps"}, {"property": "reportedTime"}], "partial"),
    ],
)
async def test_formal_validation_diagnostics_block_document_generation_and_unused_citations(
    requests, status
):
    class BlankStep(Graph):
        async def query(self, request):
            result = await super().query(request)
            text = "佛跳墙做法0属于佛跳墙，糖用量为适量，耗时半小时。步骤1没有记载内容。"
            evidence = [EvidenceReference(source_id="manual", quote=text)]
            result.sources[0].text = text
            for item in [*result.entities, *result.relations]:
                item.evidence = evidence
            result.entities[0].properties["cook_time"] = "半小时"
            result.entities.extend(
                [
                    KnowledgeEntity(id="dish-0", type="Dish", name="佛跳墙", evidence=evidence),
                    KnowledgeEntity(
                        id="step-1",
                        type="CookingStep",
                        name="第一步",
                        properties={"order": 1, "instruction": ""},
                        evidence=evidence,
                    ),
                ]
            )
            result.relations.extend(
                [
                    KnowledgeRelation(
                        id="variant-of",
                        source_id=result.entities[0].id,
                        target_id="dish-0",
                        type="VARIANT_OF",
                        evidence=evidence,
                    ),
                    KnowledgeRelation(
                        id="has-step",
                        source_id=result.entities[0].id,
                        target_id="step-1",
                        type="HAS_STEP",
                        properties={"order": 1},
                        evidence=evidence,
                    ),
                ]
            )
            return result

    model = Model(
        {"facts": True, "entity_mentions": ["佛跳墙"], "requests": requests, "documents": True}
    )
    documents = Documents()
    answer = await query_service(graph=BlankStep(), model=model, documents=documents).answer(
        "核对佛跳墙步骤资料并结合原文说明"
    )
    assert documents.queries
    assert not model.generations
    semantic = answer.metadata["semantic_evaluation"]
    assert semantic["diagnostics"]
    assert answer.metadata["status"] == semantic["status"] == status
    assert answer.message == semantic["message"]
    assert answer.sources == semantic["sources"]
    assert all(source["backend"] == "neo4j" for source in answer.sources)
    if status == "partial":
        assert "半小时" in answer.message


@pytest.mark.asyncio
@pytest.mark.parametrize("qualifier", [{"unit": "g"}, {"target": "糖"}])
async def test_unit_on_nonquantity_property_is_clarified_instead_of_ignored(qualifier):
    graph = Graph()
    model = Model(
        {
            "facts": True,
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "reportedTime", **qualifier}],
        }
    )
    answer = await query_service(graph=graph, model=model).answer("请把佛跳墙耗时按克回答")
    assert answer.route == "clarification"
    assert not graph.queries


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "projection", [{"property": "ingredientQuantity", "target": "糖"}, {"property": "reportedTime"}]
)
async def test_count_does_not_silently_discard_requested_property_qualifiers(projection):
    graph = Graph()
    model = Model(
        {
            "facts": True,
            "operation": "count",
            "entity_type": "RecipeVariant",
            "requests": [projection],
        }
    )
    answer = await query_service(graph=graph, model=model).answer("统计全部做法中指定属性的数量")
    assert answer.route == "clarification"
    assert not graph.queries


@pytest.mark.asyncio
async def test_formal_lookup_requires_business_requests_before_querying_complete_facts():
    graph = Graph()
    model = Model(
        {
            "facts": True,
            "entity_type": "RecipeVariant",
            "entity_mentions": ["佛跳墙"],
            "requests": [],
        }
    )
    answer = await query_service(graph=graph, model=model).answer("核对佛跳墙资料中的内容")
    assert answer.route == "clarification"
    assert "业务属性" in answer.message
    assert not graph.queries
    assert not model.generations


@pytest.mark.asyncio
async def test_property_bindings_and_tbox_edits_change_query_scope_without_prompt_edits(
    tmp_path,
):
    from pathlib import Path

    from rdflib import RDFS, Literal, Namespace
    from rdflib import Graph as RdfGraph
    from rdflib.collection import Collection

    from gustobot.application.services.knowledge_query import KnowledgeQueryService
    from gustobot.domain.formal_ontology import load_formal_ontology

    ontology_dir = Path(__file__).resolve().parents[1] / "gustobot/config/ontologies"
    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        (tmp_path / name).write_bytes((ontology_dir / name).read_bytes())
    rdf = RdfGraph().parse(tmp_path / "recipes.ttl", format="turtle")
    recipe = Namespace("https://gustobot.org/ontology/recipes#")
    binding = Namespace("https://gustobot.org/ontology/binding#")
    rdf.remove((recipe.BrownSugarIngredient, RDFS.subClassOf, recipe.SugarIngredient))
    rdf.add((recipe.BrownSugarIngredient, RDFS.subClassOf, recipe.Ingredient))
    rdf.set((recipe.IngredientQuantityProperty, binding.relation, recipe.HAS_MAIN_INGREDIENT))
    fields = rdf.value(recipe.IngredientQuantityProperty, binding.fields)
    assert fields is not None
    values = [
        value for value in Collection(rdf, fields) if str(value).startswith("HAS_MAIN_INGREDIENT.")
    ]
    Collection(rdf, fields).clear()
    Collection(rdf, fields, [Literal(str(value)) for value in values])
    rdf.serialize(tmp_path / "recipes.ttl", format="turtle")
    changed_domain = load_formal_ontology(
        tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl"
    ).domain_definition()
    request = {
        "facts": True,
        "selection": "all",
        "requests": [{"property": "ingredientQuantity", "target": "糖类"}],
        "conditions": [{"property": "ingredientQuantity", "target": "糖类"}],
    }
    original_graph, changed_graph = Graph(), Graph()
    await query_service(graph=original_graph, model=Model(request)).answer("列出所有糖类用量")
    await KnowledgeQueryService(
        changed_domain,
        graph_store=changed_graph,
        documents=Documents(),
        model=Model(request),
    ).answer("列出所有糖类用量")
    assert "红糖" in original_graph.queries[0].target_name_groups[0]
    assert "红糖" not in changed_graph.queries[0].target_name_groups[0]
    assert changed_graph.queries[0].relation_types == ["HAS_MAIN_INGREDIENT"]


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_set_document_lookup_waits_for_the_fact_scope_and_skips_empty_scope(empty):
    completed = []

    class ScopedGraph(Graph):
        async def query(self, request):
            result = await super().query(request)
            completed.append(True)
            return result

    class ScopedDocuments(Documents):
        async def search(self, query, **kwargs):
            assert completed == [True]
            assert kwargs["entity_ids"] == ["recipe-0"]
            return await super().search(query, **kwargs)

    graph, documents = ScopedGraph(empty=empty), ScopedDocuments()
    model = Model(
        {
            "facts": True,
            "selection": "all",
            "operation": "count",
            "entity_type": "RecipeVariant",
            "documents": True,
        }
    )
    answer = await query_service(graph=graph, documents=documents, model=model).answer(
        "统计全部做法并核对原文"
    )
    assert bool(documents.queries) is not empty
    assert len(model.generations) == (0 if empty else 1)
    assert answer.metadata["model_calls"] == (1 if empty else 2)
    assert answer.metadata["status"] == ("no_results" if empty else "success")


@pytest.mark.asyncio
async def test_fact_revision_conflict_marks_linking_stale_and_never_generates_an_answer():
    from gustobot.infrastructure.knowledge.graph_store import GraphRevisionConflict

    class ChangedGraph(Graph):
        async def query(self, request):
            assert request.expected_graph_revision == 1
            raise GraphRevisionConflict("graph changed during retrieval")

    graph, model = ChangedGraph(), Model({})
    service = query_service(graph=graph, model=model)
    service.linker, _ = semantic_linker_for(graph, exact=True)
    answer = await service.answer("佛跳墙加多少糖？")
    assert answer.metadata["status"] == "retrieval_unavailable"
    assert answer.metadata["linking"]["status"] == "stale"
    assert answer.metadata["model_calls"] == 0
    assert answer.sources == [] and not model.generations


@pytest.mark.asyncio
async def test_bound_target_executes_the_canonical_name_and_preserves_the_users_plan():
    from gustobot.domain.linking import CatalogRecord, LinkedCandidate, LinkResolution

    class WhiteSugarGraph(Graph):
        async def query(self, request):
            result = await super().query(request)
            result.entities[1].name = "白糖"
            return result

    graph = WhiteSugarGraph()
    linker, _ = semantic_linker_for(graph, exact=True)
    domain = get_domain_definition()
    assert domain.semantic_model is not None
    target = LinkedCandidate(
        record=CatalogRecord.create(
            domain_id=domain.id,
            ontology_version=domain.version,
            ontology_fingerprint=domain.semantic_model.fingerprint,
            kind="entity",
            ref_kind="entity",
            ref_id="white-sugar-id",
            object_type="Ingredient",
            label="白糖",
            graph_revision=1,
        )
    )
    resolve_anchor = linker.resolve

    async def supplement(references, *, context):
        return context

    async def resolve(references, *, context):
        if references[0].expected_type == "Ingredient":
            return LinkResolution(
                references=[references[0].model_copy(update={"ref_id": target.ref_id})],
                candidates=[target],
                status="resolved",
            )
        return await resolve_anchor(references, context=context)

    linker.supplement, linker.resolve = supplement, resolve
    model = Model(
        {
            "facts": True,
            "entity_mentions": ["佛跳墙"],
            "requests": [{"property": "ingredientQuantity", "target": "白唐"}],
        }
    )
    service = query_service(graph=graph, model=model)
    service.linker = linker
    prepared = await service.prepare("查询佛跳墙中白唐的用量")
    assert prepared.semantic_plan.requests[0].target == "白唐"
    assert prepared.execution_semantic_plan.requests[0].target == "白糖"
    assert "白糖" in graph.queries[0].projections[0].target_names
    assert "适量" in prepared.semantic_evaluation.message
    assert prepared.bound_targets["白唐"]["ref_id"] == "white-sugar-id"
    assert prepared.analysis_calls == len(model.analysis) == 1 and not model.generations
