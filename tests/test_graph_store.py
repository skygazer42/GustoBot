"""Typed graph queries validate before crossing the Neo4j driver boundary."""

import asyncio
import importlib
import importlib.util
from typing import Any

import pytest

from gustobot.domain.knowledge import DomainDefinition, KnowledgeGraph


def graph_api():
    name = "gustobot.infrastructure.knowledge.graph_store"
    assert importlib.util.find_spec(name) is not None, "The Neo4j graph store is missing"
    return importlib.import_module(name)


@pytest.fixture
def domain():
    return DomainDefinition.model_validate(
        {
            "id": "graph-store-unit",
            "name": "Recipes",
            "description": "Source-backed recipes",
            "entity_types": {
                "Recipe": {
                    "description": "A recipe variant",
                    "properties": {
                        "cuisine": {"type": "string"},
                        "minutes": {"type": "integer"},
                        "verified": {"type": "boolean"},
                    },
                },
                "Ingredient": {"description": "An ingredient", "properties": {}},
            },
            "relation_types": {
                "HAS_INGREDIENT": {
                    "description": "Recipe ingredient and its quantity",
                    "source_types": ["Recipe"],
                    "target_types": ["Ingredient"],
                    "properties": {"amount_text": {"type": "string"}},
                }
            },
            "document_scope": "Recipe documents",
        }
    )


class RecordingResult:
    def __init__(self, rows):
        self.rows = rows

    async def data(self):
        return self.rows

    async def consume(self):
        return None


class RecordingSession:
    def __init__(self, driver):
        self.driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.driver.exits += 1

    async def execute_read(self, operation, *args):
        return await operation(self, *args)

    async def execute_write(self, operation, *args):
        return await operation(self, *args)

    async def run(self, query, parameters=None, **kwargs):
        self.driver.statements.append((query, dict(parameters or {}, **kwargs)))
        if self.driver.failure is not None:
            raise self.driver.failure
        if self.driver.evidence_rows is not None and "MATCH (e:GustoEvidence" in query:
            return RecordingResult(self.driver.evidence_rows)
        return RecordingResult(self.driver.rows)


class RecordingDriver:
    def __init__(self, *, rows=None, evidence_rows=None, failure=None):
        self.rows = rows if rows is not None else [{"total": 0, "nodes": [], "relations": []}]
        self.failure = failure
        self.evidence_rows = evidence_rows
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.databases: list[str] = []
        self.exits = 0
        self.close_calls = 0

    def session(self, *, database):
        self.databases.append(database)
        return RecordingSession(self)

    async def close(self):
        self.close_calls += 1


@pytest.mark.asyncio
async def test_property_projection_does_not_require_unrequested_mandatory_edges(domain):
    api = graph_api()
    domain.relation_types["HAS_INGREDIENT"].cardinality.minimum = 1
    driver = RecordingDriver(
        rows=[
            {
                "total": 1,
                "nodes": [
                    {
                        "id": "recipe",
                        "entity_type": "Recipe",
                        "name": "Recipe",
                        "aliases": [],
                        "p__minutes": 10,
                    }
                ],
                "relations": [],
            }
        ],
        evidence_rows=[
            {
                "owner_kind": "entity",
                "owner_id": "recipe",
                "source_id": "doc",
                "quote": "Recipe",
                "id": "doc",
                "text": "Recipe has sugar.",
                "uri": None,
            }
        ],
    )
    result = await make_store(api, domain, driver).query(api.FactQuery(anchor_ids=["recipe"]))
    assert [item.id for item in result.entities] == ["recipe"]
    assert result.relations == []
    assert result.total == 1


def make_store(api, domain, driver):
    return api.Neo4jGraphStore(
        domain,
        uri="bolt://unused.invalid:7687",
        user="test",
        password="unused-test-password",
        database="isolated",
        driver=driver,
    )


@pytest.mark.asyncio
async def test_empty_query_reports_a_successful_domain_scoped_miss(domain):
    api = graph_api()
    driver = RecordingDriver()
    result = await make_store(api, domain, driver).query(api.FactQuery(entity_type="Recipe"))
    assert result.model_dump() == {
        "entities": [],
        "relations": [],
        "sources": [],
        "total": 0,
        "truncated": False,
        "ontology_version": domain.version,
        "numeric_coverage": [],
        "numeric_values": [],
    }
    assert driver.databases == ["isolated"]
    assert all(params["domain_id"] == domain.id for _, params in driver.statements)


@pytest.mark.parametrize(
    "query",
    [
        {"entity_type": "Recipe) MATCH (x) DETACH DELETE x //"},
        {"relation_types": ["UNKNOWN"]},
        {
            "entity_type": "Recipe",
            "filters": [{"property": "secret", "op": "eq", "value": 1}],
        },
        {"filters": [{"property": "minutes", "op": "eq", "value": 1}]},
        {"target_names": ["pork"]},
        {"max_hops": 2},
        {
            "entity_type": "Recipe",
            "filters": [{"property": "minutes", "op": "eq", "value": True}],
        },
        {
            "entity_type": "Recipe",
            "filters": [{"property": "verified", "op": "gt", "value": True}],
        },
    ],
)
@pytest.mark.asyncio
async def test_unsupported_clauses_are_rejected_before_database_access(domain, query):
    api = graph_api()
    driver = RecordingDriver()
    with pytest.raises(ValueError):
        await make_store(api, domain, driver).query(api.FactQuery.model_validate(query))
    assert driver.statements == []


@pytest.mark.parametrize(
    "payload",
    [
        {"limit": 0},
        {"limit": 101},
        {"max_hops": 0},
        {"max_hops": 4},
        {"operation": "cypher"},
        {"cypher": "MATCH (n) RETURN n"},
        {"filters": [{"property": "minutes", "op": "eq", "value": [1]}]},
        {"filters": [{"property": "minutes", "op": "in", "value": 1}]},
        {"anchor_ids": [""]},
        {"anchor_names": [" "]},
        {"anchor_names": [f"name-{index}" for index in range(11)]},
        {"target_names": [" "]},
        {"target_name_groups": [[]]},
        {"target_name_groups": [[" "]]},
        {"target_name_groups": [["sugar"]], "target_group_relation_types": [[]]},
        {"target_group_relation_types": [["HAS_INGREDIENT"]]},
    ],
)
def test_query_contract_rejects_unbounded_or_ambiguous_inputs(payload):
    api = graph_api()
    with pytest.raises(ValueError):
        api.FactQuery.model_validate(payload)


@pytest.mark.asyncio
async def test_resolver_parameterizes_mentions_and_returns_all_candidates(domain):
    api = graph_api()
    mention = "红烧肉') MATCH (x) DETACH DELETE x //"
    driver = RecordingDriver(
        rows=[
            {
                "id": "recipe-home",
                "type": "Recipe",
                "name": "红烧肉家常版",
                "aliases": ["红烧肉"],
                "source_ids": [],
                "source_uris": [],
                "summary": {"cook_time": None, "source_record_id": None},
            },
            {
                "id": "recipe-chef",
                "type": "Recipe",
                "name": "红烧肉厨师版",
                "aliases": ["红烧肉"],
                "source_ids": [],
                "source_uris": [],
                "summary": {"cook_time": None, "source_record_id": None},
            },
        ]
    )
    candidates = await make_store(api, domain, driver).resolve_entities(mention, ["Recipe"])
    assert [item.id for item in candidates] == ["recipe-home", "recipe-chef"]
    statement, parameters = driver.statements[0]
    assert mention not in statement
    assert mention.casefold() in parameters.values()
    assert parameters["domain_id"] == domain.id


@pytest.mark.asyncio
async def test_filter_and_target_values_are_parameters(domain):
    api = graph_api()
    value = "Sichuan') DETACH DELETE n //"
    driver = RecordingDriver()
    query = api.FactQuery(
        entity_type="Recipe",
        relation_types=["HAS_INGREDIENT"],
        target_names=[value],
        filters=[api.FactFilter(property="cuisine", op="eq", value=value)],
    )
    await make_store(api, domain, driver).query(query)
    for statement, parameters in driver.statements:
        assert value not in statement
        assert parameters["domain_id"] == domain.id
    assert any(value in parameters.values() for _, parameters in driver.statements)


@pytest.mark.asyncio
async def test_target_groups_compile_as_conjunctions_of_parameterized_alternatives(
    domain,
):
    api = graph_api()
    injected = "Sugar') MATCH (n) DETACH DELETE n //"
    driver = RecordingDriver()
    await make_store(api, domain, driver).query(
        api.FactQuery(
            entity_type="Recipe",
            relation_types=["HAS_INGREDIENT"],
            target_names=["salt"],
            target_name_groups=[["brown sugar", injected], ["pork", "pork belly"]],
            operation="count",
        )
    )
    statement, parameters = driver.statements[0]
    assert injected not in statement
    for group in (["salt"], ["brown sugar", injected.casefold()], ["pork", "pork belly"]):
        assert group in parameters.values()
    assert parameters["ontology_version"] == domain.version


@pytest.mark.asyncio
async def test_optional_relation_projection_keeps_anchor_and_truncates_excess_paths(
    domain,
):
    api = graph_api()
    driver = RecordingDriver(
        rows=[
            {
                "total": 1,
                "path_total": 3,
                "nodes": [
                    {
                        "id": "recipe",
                        "entity_type": "Recipe",
                        "name": "Recipe",
                        "aliases": [],
                        "p__minutes": 10,
                    }
                ],
                "relations": [],
            }
        ],
        evidence_rows=[
            {
                "owner_kind": "entity",
                "owner_id": "recipe",
                "source_id": "doc",
                "quote": "Recipe",
                "id": "doc",
                "text": "Recipe takes ten minutes.",
                "uri": None,
            }
        ],
    )
    result = await make_store(api, domain, driver).query(
        api.FactQuery(
            anchor_ids=["recipe"],
            relation_types=["HAS_INGREDIENT"],
            include_anchors=True,
            limit=1,
        )
    )
    assert result.entities[0].properties["minutes"] == 10
    assert result.truncated is True


@pytest.mark.asyncio
async def test_each_positive_target_group_uses_its_bound_relation_set(domain):
    api = graph_api()
    domain.relation_types["OTHER_INGREDIENT"] = domain.relation_types["HAS_INGREDIENT"].model_copy()
    driver = RecordingDriver()
    await make_store(api, domain, driver).query(
        api.FactQuery(
            relation_types=["HAS_INGREDIENT", "OTHER_INGREDIENT"],
            target_name_groups=[["sugar"]],
            target_group_relation_types=[["HAS_INGREDIENT"]],
            include_anchors=True,
        )
    )
    _, parameters = driver.statements[0]
    assert ["HAS_INGREDIENT"] in parameters.values()
    assert ["HAS_INGREDIENT", "OTHER_INGREDIENT"] in parameters.values()


@pytest.mark.asyncio
async def test_projection_targets_are_optional_parameterized_and_separate_from_filters(domain):
    api = graph_api()
    driver = RecordingDriver()
    injected = "sugar') MATCH (n) DETACH DELETE n //"
    await make_store(api, domain, driver).query(
        api.FactQuery.model_validate(
            {
                "anchor_ids": ["recipe"],
                "relation_types": ["HAS_INGREDIENT"],
                "include_anchors": True,
                "projections": [
                    {
                        "relation_types": ["HAS_INGREDIENT"],
                        "target_names": ["brown sugar", injected],
                    }
                ],
            }
        )
    )
    statement, parameters = driver.statements[0]
    assert injected not in statement
    assert [
        {"relation_types": ["HAS_INGREDIENT"], "target_names": ["brown sugar", injected.casefold()]}
    ] in parameters.values()


@pytest.mark.asyncio
async def test_bad_evidence_is_rejected_before_schema_or_write(domain):
    api = graph_api()
    graph = KnowledgeGraph.model_validate(
        {
            "entities": [
                {
                    "id": "recipe-1",
                    "type": "Recipe",
                    "name": "红烧肉",
                    "evidence": [{"source_id": "doc", "quote": "invented"}],
                }
            ],
            "relations": [],
            "sources": [{"id": "doc", "text": "红烧肉需要猪肉。"}],
        }
    )
    driver = RecordingDriver()
    with pytest.raises(ValueError, match="quote"):
        await make_store(api, domain, driver).upsert(graph)
    assert driver.statements == []


@pytest.mark.parametrize(
    "failure", [RuntimeError("database unavailable"), asyncio.CancelledError()]
)
@pytest.mark.asyncio
async def test_database_errors_and_cancellation_propagate_and_release_session(domain, failure):
    api = graph_api()
    driver = RecordingDriver(failure=failure)
    with pytest.raises(type(failure)) as raised:
        await make_store(api, domain, driver).query(api.FactQuery())
    assert raised.value is failure
    assert driver.exits == 1


@pytest.mark.asyncio
async def test_store_closes_only_its_owned_driver_once(domain, monkeypatch):
    api = graph_api()
    owned = RecordingDriver()
    monkeypatch.setattr(api.AsyncGraphDatabase, "driver", lambda *args, **kwargs: owned)
    store = api.Neo4jGraphStore(domain, uri="bolt://unused.invalid", user="test", password="test")
    await store.close()
    await store.close()
    assert owned.close_calls == 1
    with pytest.raises(RuntimeError, match="closed"):
        await store.query(api.FactQuery())
    borrowed = RecordingDriver()
    store = make_store(api, domain, borrowed)
    await store.close()
    assert borrowed.close_calls == 0
