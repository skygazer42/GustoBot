"""Neo4j behavior, using only explicitly supplied isolated-test credentials.

Set GUSTOBOT_TEST_NEO4J_CONFIG to a JSON file containing uri, user,
password and optionally database. Every test uses disposable UUID domain IDs.
"""

import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from anyio import create_task_group
from neo4j import AsyncGraphDatabase

from gustobot.domain.knowledge import DomainDefinition, KnowledgeGraph, validate_graph


def api():
    from gustobot.infrastructure.knowledge import graph_store

    return graph_store


def recipe_domain(domain_id):
    return DomainDefinition.model_validate(
        {
            "id": domain_id,
            "name": "Isolated graph tests",
            "description": "Disposable facts",
            "entity_types": {
                "Recipe": {
                    "description": "Recipe variant",
                    "properties": {
                        "minutes": {"type": "integer"},
                        "cuisine": {"type": "string"},
                        "verified": {"type": "boolean"},
                    },
                },
                "Ingredient": {"description": "Ingredient", "properties": {}},
                "Category": {"description": "Ingredient category", "properties": {}},
            },
            "relation_types": {
                "HAS_INGREDIENT": {
                    "description": "Recipe quantity",
                    "source_types": ["Recipe"],
                    "target_types": ["Ingredient"],
                    "properties": {"amount_text": {"type": "string"}},
                },
                "IN_CATEGORY": {
                    "description": "Ingredient category",
                    "source_types": ["Ingredient"],
                    "target_types": ["Category"],
                },
            },
            "document_scope": "Isolated documents",
        }
    )


def recipe_graph():
    text = (
        "红烧肉家常版用猪肉500克和糖20克，需45分钟；红烧肉厨师版用猪肉600克和糖，需60分钟。"
        "红烧肉快手版用猪肉300克和盐2克，需20分钟。糖属于调味。"
    )
    evidence = [{"source_id": "original", "quote": text}]
    entities = [
        {
            "id": "recipe-home",
            "type": "Recipe",
            "name": "红烧肉家常版",
            "aliases": ["红烧肉"],
            "properties": {"minutes": 45, "cuisine": "Chinese", "verified": False},
            "evidence": evidence,
        },
        {
            "id": "recipe-chef",
            "type": "Recipe",
            "name": "红烧肉厨师版",
            "aliases": ["红烧肉"],
            "properties": {"minutes": 60, "cuisine": "Chinese", "verified": True},
            "evidence": evidence,
        },
        {
            "id": "recipe-quick",
            "type": "Recipe",
            "name": "红烧肉快手版",
            "aliases": ["红烧肉"],
            "properties": {"minutes": 20, "cuisine": "Chinese"},
            "evidence": evidence,
        },
        {
            "id": "pork",
            "type": "Ingredient",
            "name": "猪肉",
            "aliases": ["五花肉"],
            "evidence": evidence,
        },
        {
            "id": "sugar",
            "type": "Ingredient",
            "name": "糖",
            "aliases": ["冰糖"],
            "evidence": evidence,
        },
        {"id": "salt", "type": "Ingredient", "name": "盐", "evidence": evidence},
        {"id": "seasoning", "type": "Category", "name": "调味", "evidence": evidence},
    ]
    relations = []
    for source, target, amount in [
        ("recipe-home", "pork", "500克"),
        ("recipe-home", "sugar", "20克"),
        ("recipe-chef", "pork", "600克"),
        ("recipe-chef", "sugar", None),
        ("recipe-quick", "pork", "300克"),
        ("recipe-quick", "salt", "2克"),
    ]:
        relations.append(
            {
                "id": f"{source}-{target}",
                "source_id": source,
                "target_id": target,
                "type": "HAS_INGREDIENT",
                "properties": {} if amount is None else {"amount_text": amount},
                "evidence": evidence,
            }
        )
    relations.append(
        {
            "id": "sugar-category",
            "source_id": "sugar",
            "target_id": "seasoning",
            "type": "IN_CATEGORY",
            "evidence": evidence,
        }
    )
    return KnowledgeGraph.model_validate(
        {
            "entities": entities,
            "relations": relations,
            "sources": [{"id": "original", "text": text, "uri": "recipe.json"}],
        }
    )


@pytest_asyncio.fixture
async def isolated_graph():
    config_path = os.environ.get("GUSTOBOT_TEST_NEO4J_CONFIG")
    if config_path is None:
        pytest.skip("An explicit isolated Neo4j test configuration is required")
        return
    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    database = config.get("database", "neo4j")
    driver = AsyncGraphDatabase.driver(config["uri"], auth=(config["user"], config["password"]))
    async with AsyncExitStack() as resources:
        resources.push_async_callback(driver.close)
        domains = []

        def new_store(selected_domain=None):
            identifier = f"graph-test-{uuid4().hex}"
            domain = (
                recipe_domain(identifier)
                if selected_domain is None
                else selected_domain.model_copy(update={"id": identifier})
            )
            domains.append(domain.id)
            store = api().Neo4jGraphStore(
                domain,
                database=database,
                driver=driver,
                **{key: config[key] for key in ("uri", "user", "password")},
            )
            resources.push_async_callback(store.close)
            return domain, store

        domain, store = new_store()
        graph = recipe_graph()

        async def clear_domains():
            async with driver.session(database=database) as session:
                result = await session.run(
                    "MATCH (n) WHERE n.domain_id IN $domains DETACH DELETE n",
                    domains=domains,
                )
                await result.consume()

        resources.push_async_callback(clear_domains)
        await store.upsert(graph)
        yield SimpleNamespace(
            domain=domain,
            store=store,
            graph=graph,
            driver=driver,
            database=database,
            new_store=new_store,
        )


@pytest.mark.asyncio
async def test_relation_quantity_uses_aliases_and_returns_original_source(
    isolated_graph,
):
    scope = isolated_graph
    result = await scope.store.query(
        api().FactQuery(
            anchor_ids=["recipe-home"],
            relation_types=["HAS_INGREDIENT"],
            target_names=["五花肉"],
        )
    )
    assert result.total == 1
    assert {item.id for item in result.entities} == {"recipe-home", "pork"}
    assert [(item.id, item.properties) for item in result.relations] == [
        ("recipe-home-pork", {"amount_text": "500克"})
    ]
    assert result.sources == scope.graph.sources
    validate_graph(
        scope.domain,
        KnowledgeGraph(
            entities=result.entities, relations=result.relations, sources=result.sources
        ),
    )


@pytest.mark.asyncio
async def test_property_lookup_and_full_domain_counts_precede_display_limit(
    isolated_graph,
):
    result = await isolated_graph.store.query(
        api().FactQuery(entity_type="Recipe", operation="count", limit=1)
    )
    assert result.total == 3
    assert result.truncated is True
    assert len(result.entities) == 1
    assert result.relations == []
    item = next(entity for entity in result.entities if entity.id == "recipe-chef")
    assert item.properties == {"minutes": 60, "cuisine": "Chinese", "verified": True}


@pytest.mark.asyncio
async def test_fullwidth_names_aliases_and_target_groups_share_canonical_name_matching(
    isolated_graph,
):
    text = "Ｒｅｃｉｐｅ　Ａ使用ＳＵＧＡＲ 20g。"
    evidence = [{"source_id": "fullwidth-source", "quote": text}]
    await isolated_graph.store.upsert(
        KnowledgeGraph.model_validate(
            {
                "entities": [
                    {
                        "id": "fullwidth-recipe",
                        "type": "Recipe",
                        "name": "Ｒｅｃｉｐｅ　Ａ",
                        "aliases": ["ＦＵＬＬＷＩＤＴＨ"],
                        "evidence": evidence,
                    },
                    {
                        "id": "fullwidth-sugar",
                        "type": "Ingredient",
                        "name": "ＳＵＧＡＲ",
                        "aliases": ["ＦＩＮＥ　ＳＵＧＡＲ"],
                        "evidence": evidence,
                    },
                ],
                "relations": [
                    {
                        "id": "fullwidth-use",
                        "source_id": "fullwidth-recipe",
                        "target_id": "fullwidth-sugar",
                        "type": "HAS_INGREDIENT",
                        "properties": {"amount_text": "20g"},
                        "evidence": evidence,
                    }
                ],
                "sources": [{"id": "fullwidth-source", "text": text}],
            }
        )
    )
    assert [
        item.id for item in await isolated_graph.store.resolve_entities("Recipe A", ["Recipe"])
    ] == ["fullwidth-recipe"]
    assert [
        item.id for item in await isolated_graph.store.resolve_entities("fullwidth", ["Recipe"])
    ] == ["fullwidth-recipe"]
    result = await isolated_graph.store.query(
        api().FactQuery(
            entity_type="Recipe",
            anchor_names=["Recipe A"],
            relation_types=["HAS_INGREDIENT"],
            target_name_groups=[["sugar", "fine sugar"]],
            operation="count",
        )
    )
    assert result.total == 1


@pytest.mark.asyncio
async def test_target_groups_use_or_names_and_and_conditions_over_full_scope(
    isolated_graph,
):
    result = await isolated_graph.store.query(
        api().FactQuery(
            entity_type="Recipe",
            relation_types=["HAS_INGREDIENT"],
            target_name_groups=[["糖", "盐"], ["五花肉", "不存在的食材"]],
            operation="count",
            limit=1,
        )
    )
    assert result.total == 3
    assert result.truncated is True
    assert len(result.entities) == 1
    narrowed = await isolated_graph.store.query(
        api().FactQuery(
            entity_type="Recipe",
            relation_types=["HAS_INGREDIENT"],
            target_names=["糖"],
            target_name_groups=[["猪肉", "不存在的食材"]],
            operation="count",
        )
    )
    assert narrowed.total == 2
    injected = await isolated_graph.store.query(
        api().FactQuery(
            relation_types=["HAS_INGREDIENT"],
            target_name_groups=[["糖') MATCH (n) DETACH DELETE n //"]],
            operation="count",
        )
    )
    assert injected.total == 0


@pytest.mark.asyncio
async def test_optional_projection_keeps_recorded_anchor_when_no_edge_matches(
    isolated_graph,
):
    result = await isolated_graph.store.query(
        api().FactQuery(
            anchor_ids=["recipe-quick"],
            entity_type="Recipe",
            relation_types=["IN_CATEGORY"],
            include_anchors=True,
        )
    )
    assert result.total == 1
    assert result.truncated is False
    assert result.relations == []
    assert [(item.id, item.properties["minutes"]) for item in result.entities] == [
        ("recipe-quick", 20)
    ]


@pytest.mark.asyncio
async def test_requested_projection_precedes_limit_despite_twenty_unrelated_edges(
    isolated_graph,
):
    graph = isolated_graph.graph.model_copy(deep=True)
    for index in range(20):
        ingredient = graph.entities[3].model_copy(deep=True)
        ingredient.id = f"unrelated-{index}"
        ingredient.name = f"其他原料{index}"
        ingredient.aliases = []
        graph.entities.append(ingredient)
        edge = graph.relations[0].model_copy(deep=True)
        edge.id = f"a-unrelated-{index:02}"
        edge.target_id = ingredient.id
        graph.relations.append(edge)
    await isolated_graph.store.upsert(graph)
    result = await isolated_graph.store.query(
        api().FactQuery.model_validate(
            {
                "anchor_ids": ["recipe-home"],
                "entity_type": "Recipe",
                "relation_types": ["HAS_INGREDIENT"],
                "include_anchors": True,
                "projections": [
                    {
                        "relation_types": ["HAS_INGREDIENT"],
                        "target_names": ["糖", "冰糖"],
                    }
                ],
                "limit": 1,
            }
        )
    )
    assert result.total == 1
    assert result.truncated is False
    assert [(edge.target_id, edge.properties["amount_text"]) for edge in result.relations] == [
        ("sugar", "20克")
    ]
    assert {entity.id for entity in result.entities} == {"recipe-home", "sugar"}


@pytest.mark.asyncio
async def test_lookup_path_count_is_distinct_and_precedes_display_limit(isolated_graph):
    result = await isolated_graph.store.query(
        api().FactQuery(entity_type="Recipe", relation_types=["HAS_INGREDIENT"], limit=1)
    )
    assert result.total == 6
    assert result.truncated is True
    assert len(result.relations) == 1
    assert len(result.entities) == 2


@pytest.mark.asyncio
async def test_all_requested_targets_and_property_filters_are_conjunctive(
    isolated_graph,
):
    graph_api = api()
    query = graph_api.FactQuery(
        entity_type="Recipe",
        relation_types=["HAS_INGREDIENT"],
        target_names=["猪肉", "冰糖"],
        operation="count",
    )
    result = await isolated_graph.store.query(query)
    assert result.total == 2
    assert {item.id for item in result.entities} == {"recipe-chef", "recipe-home"}
    query.filters = [graph_api.FactFilter(property="minutes", op="gte", value=50)]
    assert (await isolated_graph.store.query(query)).total == 1
    query.filters = [graph_api.FactFilter(property="verified", op="eq", value=False)]
    result = await isolated_graph.store.query(query)
    assert result.total == 1
    assert [item.id for item in result.entities] == ["recipe-home"]


@pytest.mark.asyncio
async def test_scalar_filter_operators_exclude_unknown_property_values(isolated_graph):
    graph_api = api()
    cases = [
        ("minutes", "eq", 45, {"recipe-home"}),
        ("minutes", "ne", 45, {"recipe-chef", "recipe-quick"}),
        ("minutes", "lt", 45, {"recipe-quick"}),
        ("minutes", "lte", 45, {"recipe-home", "recipe-quick"}),
        ("minutes", "gt", 45, {"recipe-chef"}),
        ("minutes", "gte", 45, {"recipe-chef", "recipe-home"}),
        ("minutes", "in", [20, 60], {"recipe-chef", "recipe-quick"}),
        ("verified", "ne", True, {"recipe-home"}),
    ]
    for property_name, operator, value, expected in cases:
        result = await isolated_graph.store.query(
            graph_api.FactQuery(
                entity_type="Recipe",
                filters=[graph_api.FactFilter(property=property_name, op=operator, value=value)],
            )
        )
        assert {item.id for item in result.entities} == expected


@pytest.mark.asyncio
async def test_direction_and_maximum_path_depth_are_respected(isolated_graph):
    graph_api = api()
    reverse = graph_api.FactQuery(anchor_ids=["pork"], relation_types=["HAS_INGREDIENT"])
    assert (await isolated_graph.store.query(reverse)).total == 0
    query = graph_api.FactQuery(
        anchor_ids=["recipe-home"],
        relation_types=["HAS_INGREDIENT", "IN_CATEGORY"],
        target_names=["调味"],
        max_hops=1,
    )
    assert (await isolated_graph.store.query(query)).total == 0
    query.max_hops = 2
    result = await isolated_graph.store.query(query)
    assert result.total == 1
    assert {item.id for item in result.entities} == {
        "recipe-home",
        "sugar",
        "seasoning",
    }
    assert {item.id for item in result.relations} == {
        "recipe-home-sugar",
        "sugar-category",
    }


@pytest.mark.asyncio
async def test_missing_quantity_remains_missing(isolated_graph):
    result = await isolated_graph.store.query(
        api().FactQuery(
            anchor_ids=["recipe-chef"],
            relation_types=["HAS_INGREDIENT"],
            target_names=["糖"],
        )
    )
    assert result.total == 1
    assert result.relations[0].properties == {}


@pytest.mark.asyncio
async def test_resolver_returns_variants_exact_aliases_and_partial_candidates(
    isolated_graph,
):
    store = isolated_graph.store
    assert {item.id for item in await store.resolve_entities("红烧肉", ["Recipe"])} == {
        "recipe-home",
        "recipe-chef",
        "recipe-quick",
    }
    assert [item.id for item in await store.resolve_entities("五花肉")] == ["pork"]
    assert {item.id for item in await store.resolve_entities("红烧", ["Recipe"])} == {
        "recipe-home",
        "recipe-chef",
        "recipe-quick",
    }
    assert {item.id for item in await store.resolve_entities("红烧肉') DETACH DELETE n //")} == {
        "recipe-home",
        "recipe-chef",
        "recipe-quick",
    }
    assert (await store.query(api().FactQuery(operation="count"))).total == 7


@pytest.mark.asyncio
async def test_resolver_recalls_mentions_inside_whole_questions_without_choosing(
    isolated_graph,
):
    store = isolated_graph.store
    candidates = await store.resolve_entities("红烧肉加多少糖", ["Recipe"])
    assert {item.id for item in candidates} == {
        "recipe-home",
        "recipe-chef",
        "recipe-quick",
    }
    candidates = await store.resolve_entities("红烧肉家常版加多少糖", ["Recipe"])
    assert candidates[0].id == "recipe-home"
    assert len(candidates) == 3
    assert [item.id for item in await store.resolve_entities("五花肉用多少")] == ["pork"]


@pytest.mark.asyncio
async def test_reimports_are_idempotent_and_merge_multi_source_evidence(isolated_graph):
    scope = isolated_graph
    result = await scope.store.upsert(scope.graph)
    assert result.model_dump() == {"entities": 7, "relations": 7, "sources": 1}
    another = scope.graph.model_copy(deep=True)
    another.sources[0].id = "second"
    another.sources[0].uri = "second.json"
    for fact in [*another.entities, *another.relations]:
        fact.evidence[0].source_id = "second"
    await scope.store.upsert(another)
    await scope.store.upsert(another)
    result = await scope.store.query(
        api().FactQuery(
            anchor_ids=["recipe-home"],
            relation_types=["HAS_INGREDIENT"],
            target_names=["猪肉"],
        )
    )
    assert result.total == 1
    assert {source.id for source in result.sources} == {"original", "second"}
    assert {ref.source_id for ref in result.relations[0].evidence} == {
        "original",
        "second",
    }
    assert len(result.relations[0].evidence) == 2
    assert all(
        {ref.source_id for ref in entity.evidence} == {"original", "second"}
        for entity in result.entities
    )
    candidates = await scope.store.resolve_entities("红烧肉家常版", ["Recipe"])
    candidate = next(item for item in candidates if item.id == "recipe-home")
    assert candidate.source_ids == ["original", "second"]
    assert candidate.source_uris == ["recipe.json", "second.json"]
    assert (await scope.store.query(api().FactQuery(operation="count"))).total == 7


@pytest.mark.asyncio
async def test_identical_ids_are_isolated_between_domains(isolated_graph):
    scope = isolated_graph
    other_domain, other_store = scope.new_store()
    other = scope.graph.model_copy(deep=True)
    other.entities[0].properties["minutes"] = 999
    await other_store.upsert(other)
    query = api().FactQuery(anchor_ids=["recipe-home"])
    assert (await scope.store.query(query)).entities[0].properties["minutes"] == 45
    assert (await other_store.query(query)).entities[0].properties["minutes"] == 999
    assert other_domain.id != scope.domain.id
    assert len(await scope.store.resolve_entities("红烧肉")) == 3


@pytest.mark.asyncio
async def test_source_identity_preserves_original_text(isolated_graph):
    scope = isolated_graph
    changed = scope.graph.model_copy(deep=True)
    changed.sources[0].text += "后来添加的内容。"
    with pytest.raises(ValueError, match="[Ss]ource"):
        await scope.store.upsert(changed)
    result = await scope.store.query(api().FactQuery(anchor_ids=["recipe-home"]))
    assert result.sources == scope.graph.sources


@pytest.mark.asyncio
async def test_relation_identity_conflict_rolls_back_entire_import(isolated_graph):
    scope = isolated_graph
    changed = scope.graph.model_copy(deep=True)
    changed.sources[0].id = "must-not-persist"
    changed.entities[0].name = "must-not-persist"
    for fact in [*changed.entities, *changed.relations]:
        fact.evidence[0].source_id = "must-not-persist"
    changed.relations[0].target_id = "sugar"
    with pytest.raises(ValueError, match="[Rr]elation"):
        await scope.store.upsert(changed)
    result = await scope.store.query(api().FactQuery(anchor_ids=["recipe-home"]))
    assert result.entities[0].name == "红烧肉家常版"
    assert [source.id for source in result.sources] == ["original"]
    async with scope.driver.session(database=scope.database) as session:
        records = await (
            await session.run(
                "MATCH (n {domain_id: $domain_id, id: $source_id}) RETURN count(n) AS total",
                domain_id=scope.domain.id,
                source_id="must-not-persist",
            )
        ).data()
    assert records[0]["total"] == 0


@pytest.mark.asyncio
async def test_concurrent_reimports_keep_single_fact_identities(isolated_graph):
    scope = isolated_graph
    async with create_task_group() as tasks:
        for _ in range(3):
            tasks.start_soon(scope.store.upsert, scope.graph)
    result = await scope.store.query(
        api().FactQuery(entity_type="Recipe", relation_types=["HAS_INGREDIENT"])
    )
    assert result.total == 6
    assert len(result.relations) == 6


@pytest.mark.asyncio
async def test_named_counts_include_all_matching_variants_before_display_limits(
    isolated_graph,
):
    scope = isolated_graph
    sentences = [f"佛跳墙版本{index:02d}需要{index}分钟。" for index in range(1, 13)]
    graph = KnowledgeGraph.model_validate(
        {
            "sources": [{"id": "twelve-variants", "text": "".join(sentences)}],
            "relations": [],
            "entities": [
                {
                    "id": f"named-variant-{index:02d}",
                    "type": "Recipe",
                    "name": f"佛跳墙版本{index:02d}",
                    "aliases": ["佛跳墙"],
                    "properties": {"minutes": index},
                    "evidence": [{"source_id": "twelve-variants", "quote": sentences[index - 1]}],
                }
                for index in range(1, 13)
            ],
        }
    )
    await scope.store.upsert(graph)
    candidates = await scope.store.resolve_entities("佛跳墙", ["Recipe"], limit=10)
    assert len(candidates) == 10
    assert all(candidate.source_ids == ["twelve-variants"] for candidate in candidates)
    assert all(candidate.source_uris == [] for candidate in candidates)
    result = await scope.store.query(
        api().FactQuery(entity_type="Recipe", anchor_names=["佛跳墙"], operation="count", limit=3)
    )
    assert result.total == 12
    assert len(result.entities) == 3
    assert result.truncated is True
    assert (
        await scope.store.query(
            api().FactQuery(anchor_names=["佛跳墙版本01", "红烧肉家常版"], operation="count")
        )
    ).total == 2


@pytest.mark.asyncio
async def test_ontology_version_scopes_candidates_anchors_and_every_path_member(
    isolated_graph,
):
    scope = isolated_graph
    next_domain = scope.domain.model_copy(deep=True)
    next_domain.version = "next-version"
    store = api().Neo4jGraphStore(
        next_domain,
        uri="bolt://unused.invalid",
        user="test",
        password="unused-test-password",
        database=scope.database,
        driver=scope.driver,
    )
    query = api().FactQuery(
        anchor_ids=["recipe-home"],
        relation_types=["HAS_INGREDIENT"],
        target_names=["猪肉"],
    )
    try:
        assert await store.resolve_entities("红烧肉") == []
        assert (await store.query(api().FactQuery(operation="count"))).total == 0
        assert (await store.query(query)).total == 0
        await store.upsert(scope.graph)
        assert (await scope.store.query(api().FactQuery(operation="count"))).total == 0
        assert await scope.store.resolve_entities("红烧肉") == []
        assert (await store.query(query)).total == 1
        async with scope.driver.session(database=scope.database) as session:
            await (
                await session.run(
                    "MATCH ()-[r:GUSTO_FACT {domain_id: $domain_id, id: $id}]->() SET r.ontology_version = $version",
                    domain_id=scope.domain.id,
                    id="recipe-home-pork",
                    version=scope.domain.version,
                )
            ).consume()
        assert (await store.query(query)).total == 0
        await store.upsert(scope.graph)
        async with scope.driver.session(database=scope.database) as session:
            await (
                await session.run(
                    "MATCH (n:GustoEntity {domain_id: $domain_id, id: $id}) SET n.ontology_version = $version",
                    domain_id=scope.domain.id,
                    id="pork",
                    version=scope.domain.version,
                )
            ).consume()
        assert (await store.query(query)).total == 0
        assert await store.resolve_entities("猪肉") == []
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_real_recipe_relation_projection_does_not_require_variant_shape_edges(
    isolated_graph, monkeypatch
):
    from gustobot.config import domain as configuration
    from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts

    scope = isolated_graph
    profile = Path(__file__).resolve().parents[1] / "gustobot/config/domains/recipes.yaml"
    monkeypatch.setattr(
        configuration, "settings", SimpleNamespace(KNOWLEDGE_DOMAIN_FILE=str(profile))
    )
    _, store = scope.new_store(configuration.get_domain_definition())
    graph = recipe_to_facts(
        "糖水",
        {"主食材": [["水", "一碗"]], "辅料": [["糖", "10克"]], "做法": "1:加入糖。"},
    )
    variant = next(entity for entity in graph.entities if entity.type == "RecipeVariant")
    try:
        await store.upsert(graph)
        result = await store.query(
            api().FactQuery(
                anchor_ids=[variant.id],
                relation_types=["HAS_AUX_INGREDIENT"],
                target_names=["糖"],
            )
        )
        assert result.total == 1
        assert [relation.type for relation in result.relations] == ["HAS_AUX_INGREDIENT"]
        assert result.relations[0].properties["amount_text"] == "10克"
        assert {entity.type for entity in result.entities} == {
            "RecipeVariant",
            "Ingredient",
        }
        assert result.sources == graph.sources
    finally:
        await store.close()


def constraint_domain(domain_id):
    return DomainDefinition.model_validate(
        {
            "id": domain_id,
            "version": "constraint-test",
            "name": "Constrained recipe facts",
            "description": "Cross-import constraints",
            "document_scope": "Recipe source assertions",
            "entity_types": {
                "RecipeVariant": {
                    "description": "Recipe variant",
                    "properties": {"minutes": {"type": "integer"}},
                },
                "Dish": {"description": "Dish concept", "properties": {}},
                "CookingStep": {"description": "Step occurrence", "properties": {}},
            },
            "relation_types": {
                "VARIANT_OF": {
                    "description": "Variant concept",
                    "source_types": ["RecipeVariant"],
                    "target_types": ["Dish"],
                    "cardinality": {"max": 1},
                },
                "HAS_STEP": {
                    "description": "Step order",
                    "source_types": ["RecipeVariant"],
                    "target_types": ["CookingStep"],
                    "properties": {"order": {"type": "integer"}},
                },
            },
            "rules": [
                {
                    "id": "step-order-unique",
                    "kind": "unique_relation_property",
                    "relation": "HAS_STEP",
                    "property": "order",
                }
            ],
        }
    )


@pytest_asyncio.fixture
async def same_name_recipe_versions(isolated_graph, monkeypatch):
    from gustobot.config import domain as configuration
    from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts

    scope = isolated_graph
    profile = Path(__file__).resolve().parents[1] / "gustobot/config/domains/recipes.yaml"
    monkeypatch.setattr(
        configuration, "settings", SimpleNamespace(KNOWLEDGE_DOMAIN_FILE=str(profile))
    )
    domain, store = scope.new_store(configuration.get_domain_definition())
    quick = recipe_to_facts(
        "佛跳墙",
        {
            "id": "quick-record",
            "source_uri": "https://recipes.test/quick",
            "耗时": "半小时",
            "主食材": [["鸡肉", "100克"]],
            "做法": "1:加入鸡肉。",
        },
    )
    slow = recipe_to_facts(
        "佛跳墙",
        {
            "id": "slow-record",
            "source_uri": "https://recipes.test/slow",
            "耗时": "数天",
            "主食材": [["鲍鱼", "2只"]],
            "做法": "1:准备鲍鱼。",
        },
    )
    try:
        await store.upsert(quick)
        await store.upsert(slow)
        yield SimpleNamespace(
            store=store,
            domain=domain,
            quick=quick,
            slow=slow,
            driver=scope.driver,
            database=scope.database,
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_same_name_recipe_candidates_have_real_sources_and_small_version_summaries(
    same_name_recipe_versions,
):
    scope = same_name_recipe_versions
    candidates = await scope.store.resolve_entities("佛跳墙", ["RecipeVariant"])
    assert len(candidates) == 2
    assert {candidate.name for candidate in candidates} == {"佛跳墙"}
    by_time = {candidate.summary["cook_time"]: candidate for candidate in candidates}
    assert by_time["半小时"].source_ids == [scope.quick.sources[0].id]
    assert by_time["半小时"].source_uris == ["https://recipes.test/quick"]
    assert by_time["半小时"].summary == {
        "cook_time": "半小时",
        "source_record_id": "quick-record",
    }
    assert by_time["数天"].source_ids == [scope.slow.sources[0].id]
    assert by_time["数天"].source_uris == ["https://recipes.test/slow"]
    assert by_time["数天"].summary == {
        "cook_time": "数天",
        "source_record_id": "slow-record",
    }


@pytest.mark.asyncio
async def test_formal_quantity_projection_finds_sugar_beyond_twenty_edges_at_limit_one(
    same_name_recipe_versions, monkeypatch
):
    from gustobot.application.services import knowledge_query
    from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts

    scope = same_name_recipe_versions
    graph = recipe_to_facts(
        "投料查询验收",
        {
            "id": "projection-rich",
            "source_uri": "https://recipes.test/projection",
            "耗时": "半小时",
            "主食材": [[f"其他原料{index}", "10克"] for index in range(20)],
            "辅料": [["红糖", "1000mg"]],
            "做法": "1:放入红糖。",
        },
    )
    anchor = next(entity for entity in graph.entities if entity.type == "RecipeVariant")
    for index, edge in enumerate(graph.relations):
        if edge.type == "HAS_MAIN_INGREDIENT":
            edge.id = f"a-unrelated-{index:02}"
        elif edge.type == "HAS_AUX_INGREDIENT":
            edge.id = "z-requested-sugar"
    await scope.store.upsert(graph)
    monkeypatch.setattr(knowledge_query.settings, "KNOWLEDGE_QUERY_LIMIT", 1)

    class Planner:
        def with_structured_output(self, schema, **kwargs):
            return self

        async def ainvoke(self, messages):
            return {
                "facts": True,
                "entity_mentions": [anchor.id],
                "requests": [{"property": "ingredientQuantity", "target": "糖类", "unit": "g"}],
            }

    def no_documents():
        raise AssertionError("A complete fact answer does not need document retrieval")

    answer = await knowledge_query.KnowledgeQueryService(
        scope.domain, graph_store=scope.store, documents=no_documents, model=Planner()
    ).answer("查询投料查询验收糖类用量，换算成克")
    assert "红糖" in answer.message and "1 g" in answer.message
    assert answer.metadata["status"] == "success"
    assert answer.metadata["facts_truncated"] is False
    assert {trace["kind"] for trace in answer.metadata["semantic_evaluation"]["derivations"]} >= {
        "inferred",
        "converted",
    }
    assert answer.sources[0]["source"] == "https://recipes.test/projection"


@pytest.mark.asyncio
async def test_explicit_full_recipe_id_selects_only_that_version_with_scoped_candidates(
    same_name_recipe_versions,
):
    scope = same_name_recipe_versions
    identifier = next(
        entity.id for entity in scope.quick.entities if entity.type == "RecipeVariant"
    )
    selected = await scope.store.resolve_entities(
        f"我选择 {identifier}，请查询佛跳墙食材", ["RecipeVariant"]
    )
    assert [candidate.id for candidate in selected] == [identifier]
    assert [
        candidate.id
        for candidate in await scope.store.resolve_entities(identifier, ["RecipeVariant"])
    ] == [identifier]
    assert await scope.store.resolve_entities(identifier[:-1], ["RecipeVariant"]) == []
    assert await scope.store.resolve_entities(identifier, ["Dish"]) == []
    assert await scope.store.resolve_entities(f"选择 {identifier}，查询佛跳墙", ["Dish"]) == []
    other_version = api().Neo4jGraphStore(
        scope.domain.model_copy(update={"version": "unpublished"}),
        uri="bolt://unused.invalid",
        user="test",
        password="unused-test-password",
        database=scope.database,
        driver=scope.driver,
    )
    other_domain = api().Neo4jGraphStore(
        scope.domain.model_copy(update={"id": scope.domain.id + "-other"}),
        uri="bolt://unused.invalid",
        user="test",
        password="unused-test-password",
        database=scope.database,
        driver=scope.driver,
    )
    try:
        async with scope.driver.session(database=scope.database) as session:
            await (
                await session.run(
                    "CREATE (:GustoEntity {domain_id: $domain_id, ontology_version: 'unpublished', "
                    "id: 'future-record', entity_type: 'RecipeVariant', name: '佛跳墙', name_key: '佛跳墙', aliases: [], alias_keys: []})",
                    domain_id=scope.domain.id,
                )
            ).consume()
        assert await other_version.resolve_entities(identifier, ["RecipeVariant"]) == []
        assert (
            await other_version.resolve_entities(
                f"选择 {identifier}，查询佛跳墙", ["RecipeVariant"]
            )
            == []
        )
        assert await other_domain.resolve_entities(identifier, ["RecipeVariant"]) == []
    finally:
        await other_version.close()
        await other_domain.close()


def constraint_graph(edge, target_id, source_id, minutes):
    text = f"做法 A 对应 {target_id}，耗时 {minutes} 分钟。"
    evidence = [{"source_id": source_id, "quote": text}]
    return KnowledgeGraph.model_validate(
        {
            "sources": [{"id": source_id, "text": text}],
            "entities": [
                {
                    "id": "variant",
                    "type": "RecipeVariant",
                    "name": "做法 A",
                    "properties": {"minutes": minutes},
                    "evidence": evidence,
                },
                {
                    "id": target_id,
                    "type": "Dish" if edge == "VARIANT_OF" else "CookingStep",
                    "name": target_id,
                    "evidence": evidence,
                },
            ],
            "relations": [
                {
                    "id": f"variant-{target_id}",
                    "source_id": "variant",
                    "target_id": target_id,
                    "type": edge,
                    "properties": {} if edge == "VARIANT_OF" else {"order": 1},
                    "evidence": evidence,
                }
            ],
        }
    )


@pytest.mark.parametrize(
    ("edge", "first_target", "second_target", "error"),
    [
        ("VARIANT_OF", "dish-one", "dish-two", "Cardinality"),
        ("HAS_STEP", "step-one", "step-two", "must be unique"),
    ],
)
@pytest.mark.asyncio
async def test_cross_batch_constraints_roll_back_the_whole_conflicting_import(
    isolated_graph, edge, first_target, second_target, error
):
    scope = isolated_graph
    domain = constraint_domain(scope.domain.id)
    store = api().Neo4jGraphStore(
        domain,
        uri="bolt://unused.invalid",
        user="test",
        password="unused-test-password",
        database=scope.database,
        driver=scope.driver,
    )
    first = constraint_graph(edge, first_target, "constraint-original", 1)
    second = constraint_graph(edge, second_target, "constraint-rejected", 999)
    validate_graph(domain, first)
    validate_graph(domain, second)
    try:
        await store.upsert(first)
        with pytest.raises(ValueError, match=error):
            await store.upsert(second)
        result = await store.query(api().FactQuery(anchor_ids=["variant"], relation_types=[edge]))
        assert result.total == 1
        assert [relation.target_id for relation in result.relations] == [first_target]
        assert (
            next(entity for entity in result.entities if entity.id == "variant").properties[
                "minutes"
            ]
            == 1
        )
        assert [source.id for source in result.sources] == ["constraint-original"]
        async with scope.driver.session(database=scope.database) as session:
            records = await (
                await session.run(
                    "MATCH (n {domain_id: $domain_id}) WHERE n.id IN $ids RETURN count(n) AS total",
                    domain_id=scope.domain.id,
                    ids=["constraint-rejected", second_target],
                )
            ).data()
        assert records[0]["total"] == 0
    finally:
        await store.close()
