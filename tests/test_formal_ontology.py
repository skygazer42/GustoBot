"""Observable contracts of the executable local recipe ontology compiler."""

import importlib
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from owlrl import DeductiveClosure, OWLRL_Semantics
from pyshacl import validate as validate_shapes
from rdflib import RDF, RDFS, BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, SH

from gustobot.config import domain as domain_config

ONTOLOGY_DIR = Path(__file__).resolve().parents[1] / "gustobot/config/ontologies"
R = Namespace("https://gustobot.org/ontology/recipes#")
B = Namespace("https://gustobot.org/ontology/binding#")


def compiler():
    assert (
        importlib.util.find_spec("gustobot.domain.formal_ontology") is not None
    ), "The default recipe domain needs an executable formal ontology compiler"
    return importlib.import_module("gustobot.domain.formal_ontology")


def load_model():
    return compiler().load_formal_ontology(
        ONTOLOGY_DIR / "recipes.ttl", ONTOLOGY_DIR / "recipes.shacl.ttl"
    )


def edited_model(tmp_path, *, ontology_edit=None, shapes_edit=None):
    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        (tmp_path / name).write_bytes((ONTOLOGY_DIR / name).read_bytes())
    for name, edit in (("recipes.ttl", ontology_edit), ("recipes.shacl.ttl", shapes_edit)):
        if edit is not None:
            graph = Graph().parse(tmp_path / name, format="turtle")
            edit(graph)
            graph.serialize(tmp_path / name, format="turtle")
    return compiler().load_formal_ontology(tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl")


def test_default_manifest_compiles_the_native_contract_and_keeps_engine_private():
    domain = domain_config.get_domain_definition()
    assert domain.semantic_model is not None
    assert domain.version == "2026-11-17.1"
    assert "IngredientUse" not in domain.entity_types
    assert "Ingredient" in domain.entity_types
    assert "semantic_model" not in domain.model_dump()
    assert "semantic_model" not in domain.model_json_schema()["properties"]
    copied = domain.model_copy(deep=True)
    copied.entity_types["RecipeVariant"].properties.clear()
    assert (
        "cook_time"
        in domain.semantic_model.domain_definition().entity_types["RecipeVariant"].properties
    )
    snapshot = domain.semantic_model.ontology_graph()
    snapshot.remove((None, None, None))
    assert len(domain.semantic_model.ontology_graph()) > 0


def test_shacl_changes_change_compiled_native_property_bounds(tmp_path):
    def edit(graph):
        node = next(
            node
            for node in graph.subjects(B.nativeField, Literal("order"))
            if (node, B.nativeOwner, Literal("CookingStep")) in graph
        )
        graph.set((node, SH.minInclusive, Literal(2)))

    changed = edited_model(tmp_path, shapes_edit=edit)
    assert changed.domain_definition().entity_types["CookingStep"].properties["order"].minimum == 2
    assert (
        load_model().domain_definition().entity_types["CookingStep"].properties["order"].minimum
        == 1
    )
    assert changed.fingerprint != load_model().fingerprint


def test_owl_class_hierarchy_drives_name_expansion_without_native_type_rewrites(tmp_path):
    model = load_model()
    assert "红糖" in model.expand_names("糖类")
    assert model.classify_name("红糖") == R.BrownSugarIngredient
    assert model.classify_name("不认识的糖浆") is None
    assert "红糖" not in model.expand_names("白糖")

    def edit(graph):
        graph.remove((R.BrownSugarIngredient, RDFS.subClassOf, R.SugarIngredient))
        graph.add((R.BrownSugarIngredient, RDFS.subClassOf, R.Ingredient))

    changed = edited_model(tmp_path, ontology_edit=edit)
    assert "红糖" not in changed.expand_names("糖类")
    assert changed.classify_name("红糖") == R.BrownSugarIngredient
    assert set(changed.domain_definition().entity_types) == set(model.native_classes)


def test_bundled_schema_axioms_actually_infer_external_types():
    model = load_model()
    graph = model.ontology_graph()
    graph.add((URIRef("urn:test:recipe"), RDF.type, R.RecipeVariant))
    graph.add((URIRef("urn:test:step"), RDF.type, R.CookingStep))
    DeductiveClosure(OWLRL_Semantics).expand(graph)
    assert (URIRef("urn:test:recipe"), RDF.type, URIRef("https://schema.org/HowTo")) in graph
    assert (URIRef("urn:test:step"), RDF.type, URIRef("https://schema.org/CreativeWork")) in graph


def test_qualitative_quantity_is_not_inferred_to_be_an_external_numeric_value():
    graph = load_model().ontology_graph()
    graph.add((URIRef("urn:test:some"), RDF.type, R.QualitativeQuantity))
    graph.add((URIRef("urn:test:exact"), RDF.type, R.NumericQuantity))
    DeductiveClosure(OWLRL_Semantics).expand(graph)
    external = URIRef("https://schema.org/QuantitativeValue")
    assert (URIRef("urn:test:some"), RDF.type, external) not in graph
    assert (URIRef("urn:test:exact"), RDF.type, external) in graph


def test_same_definitions_have_same_fingerprint_across_install_locations(tmp_path):
    assert edited_model(tmp_path).fingerprint == load_model().fingerprint


def test_asserted_axioms_remain_distinct_from_the_inference_closure():
    model = load_model()
    assert (R.BrownSugarIngredient, RDFS.subClassOf, R.Ingredient) in model.ontology_graph()
    assert (
        R.BrownSugarIngredient,
        RDFS.subClassOf,
        R.Ingredient,
    ) not in model.asserted_ontology_graph()
    assert (
        R.BrownSugarIngredient,
        RDFS.subClassOf,
        R.SugarIngredient,
    ) in model.asserted_ontology_graph()


def test_identity_rules_use_declared_keys_normalization_and_prefix(tmp_path):
    model = load_model()
    assert model.identity_id("Ingredient", {"name": "  Brown   Sugar "}) == model.identity_id(
        "Ingredient", {"name": "brown sugar"}
    )
    first = model.identity_id("RecipeVariant", {"name": "糖水", "source_id": "source:a"})
    assert first != model.identity_id("RecipeVariant", {"name": "糖水", "source_id": "source:b"})
    assert model.identity_id("CookingStep", {"parent_id": "recipe:a", "order": 0})
    with pytest.raises(ValueError, match="source_id"):
        model.identity_id("RecipeVariant", {"name": "糖水"})

    def edit(graph):
        rule = graph.value(R.Ingredient, B.identity)
        graph.set((rule, B.prefix, Literal("changed:")))

    changed = edited_model(tmp_path, ontology_edit=edit)
    assert changed.identity_id("Ingredient", {"name": "糖"}).startswith("changed:")


def test_query_bindings_units_and_reified_usage_are_machine_readable():
    model = load_model()
    binding = model.property_binding("ingredientQuantity")
    assert binding.anchor_type == "RecipeVariant"
    assert set(binding.relation_types) == {"HAS_MAIN_INGREDIENT", "HAS_AUX_INGREDIENT"}
    assert binding.target_type == "Ingredient"
    assert binding.answer_shape == R.IngredientQuantityAnswerShape
    assert "HAS_AUX_INGREDIENT.amount_text" in binding.fields
    assert model.property_binding("steps").answer_shape == R.StepsAnswerShape
    assert model.property_binding("reportedTime").fields == ("RecipeVariant.cook_time",)
    assert model.field_uri("RecipeVariant", "cook_time") == R.cook_time
    assert model.field_uri("HAS_AUX_INGREDIENT", "amount_text") == R.rawText
    assert model.native_relations["HAS_AUX_INGREDIENT"].reification_class == R.IngredientUse
    assert model.unit_spec("毫克").scale == Decimal("0.001")
    assert model.unit_spec("kg").dimension == "mass"
    assert model.unit_spec("一碗") is None
    with pytest.raises(KeyError):
        model.property_binding("invented")
    with pytest.raises(TypeError):
        model.property_bindings["invented"] = binding


def test_logical_ingredient_property_derives_its_native_query_scope():
    binding = load_model().property_binding("ingredientQuantity")
    assert binding.semantic_relations == (R.usesIngredient,)
    assert set(binding.relation_types) == {"HAS_MAIN_INGREDIENT", "HAS_AUX_INGREDIENT"}


def test_subproperty_axioms_change_the_compiled_native_relation_scope(tmp_path):
    def edit(graph):
        graph.remove((R.IngredientQuantityProperty, B.relation, None))
        graph.add((R.IngredientQuantityProperty, B.relation, R.HAS_AUX_INGREDIENT))
        graph.add((R.HAS_MAIN_INGREDIENT, RDFS.subPropertyOf, R.HAS_AUX_INGREDIENT))

    changed = edited_model(tmp_path, ontology_edit=edit)
    binding = changed.property_binding("ingredientQuantity")
    assert set(binding.relation_types) == {"HAS_MAIN_INGREDIENT", "HAS_AUX_INGREDIENT"}
    assert binding.semantic_relations == (R.HAS_AUX_INGREDIENT,)

    def remove_subproperty(graph):
        edit(graph)
        graph.remove((R.HAS_MAIN_INGREDIENT, RDFS.subPropertyOf, R.HAS_AUX_INGREDIENT))

    narrowed = edited_model(tmp_path, ontology_edit=remove_subproperty)
    assert narrowed.property_binding("ingredientQuantity").relation_types == ("HAS_AUX_INGREDIENT",)


def test_logical_relation_without_a_forward_native_projection_is_rejected(tmp_path):
    def edit(graph):
        graph.remove((R.IngredientQuantityProperty, B.relation, None))
        graph.add((R.IngredientQuantityProperty, B.relation, R.ReverseOnly))
        graph.add((R.ReverseOnly, RDF.type, OWL.ObjectProperty))
        graph.add((R.ReverseOnly, OWL.inverseOf, R.HAS_MAIN_INGREDIENT))

    with pytest.raises(ValueError, match="forward native projection"):
        edited_model(tmp_path, ontology_edit=edit)


@pytest.mark.parametrize(
    "chain",
    [
        (R.HAS_AUX_INGREDIENT,),
        (R.HAS_AUX_INGREDIENT, R.HAS_NUTRITION_PROFILE),
    ],
)
def test_mixed_supported_and_unsupported_chain_projections_are_rejected(tmp_path, chain):
    def edit(graph):
        graph.remove((R.HAS_AUX_INGREDIENT, RDFS.subPropertyOf, R.usesIngredient))
        head = BNode()
        Collection(graph, head, chain)
        graph.add((R.usesIngredient, OWL.propertyChainAxiom, head))

    with pytest.raises(ValueError, match="Unsupported.*property chain"):
        edited_model(tmp_path, ontology_edit=edit)


def test_reification_chain_cannot_silently_drop_a_native_ingredient_role(tmp_path):
    def edit(graph):
        graph.remove((R.HAS_AUX_INGREDIENT, RDFS.subPropertyOf, R.usesIngredient))

    with pytest.raises(ValueError, match="incomplete forward native projection"):
        edited_model(tmp_path, ontology_edit=edit)


def test_mixed_forward_and_native_inverse_query_projections_are_rejected(tmp_path):
    def native_inverse(graph, *, include_inverse):
        for triple in (
            (R.USED_BY, RDF.type, OWL.ObjectProperty),
            (R.USED_BY, B.nativeSymbol, Literal("USED_BY")),
            (R.USED_BY, RDFS.domain, R.Ingredient),
            (R.USED_BY, RDFS.range, R.RecipeVariant),
            (R.USED_BY, RDFS.comment, Literal("Ingredient appears in a recipe.")),
        ):
            graph.add(triple)
        if include_inverse:
            graph.add((R.USED_BY, OWL.inverseOf, R.usesIngredient))

    def endpoints(shapes):
        node = BNode()
        shapes.add((R.NativeIngredientEdgesShape, SH.property, node))
        shapes.add((node, SH.path, R.USED_BY))
        shapes.add((node, SH["class"], R.RecipeVariant))

    valid = edited_model(
        tmp_path,
        ontology_edit=lambda graph: native_inverse(graph, include_inverse=False),
        shapes_edit=endpoints,
    )
    assert valid.native_relations["USED_BY"].source_types == ("Ingredient",)
    assert valid.native_relations["USED_BY"].target_types == ("RecipeVariant",)
    with pytest.raises(ValueError, match="Unsupported query projection"):
        edited_model(
            tmp_path,
            ontology_edit=lambda graph: native_inverse(graph, include_inverse=True),
            shapes_edit=endpoints,
        )


def test_native_step_edge_shape_is_executed_on_its_reified_assertion():
    data = Graph()
    data.add((URIRef("urn:test:step-edge"), RDF.type, R.StepUse))
    data.add((URIRef("urn:test:step-edge"), R.order, Literal(0)))
    conforms, _, _ = validate_shapes(data, shacl_graph=load_model().shapes_graph())
    assert not conforms


def test_native_field_shape_without_an_execution_target_is_rejected(tmp_path):
    def edit(shapes):
        shapes.remove((R.IngredientEdgeShape, SH.targetClass, None))

    with pytest.raises(ValueError, match="executable target"):
        edited_model(tmp_path, shapes_edit=edit)


def test_native_ingredient_field_shape_runs_on_the_usage_node(tmp_path):
    def edit(shapes):
        node = next(
            node
            for node in shapes.subjects(B.nativeField, Literal("unit"))
            if (node, B.nativeOwner, Literal("HAS_AUX_INGREDIENT")) in shapes
        )
        shapes.add((node, SH.minLength, Literal(3)))

    model = edited_model(tmp_path, shapes_edit=edit)
    data = Graph()
    for triple in (
        (R.SampleRecipe, RDF.type, R.RecipeVariant),
        (R.SampleRecipe, R.VARIANT_OF, R.SampleDish),
        (R.SampleRecipe, R.evidence, R.SampleEvidence),
        (R.SampleDish, RDF.type, R.Dish),
        (R.SampleIngredient, RDF.type, R.Ingredient),
        (R.SampleUse, RDF.type, R.IngredientUse),
        (R.SampleUse, R.inRecipe, R.SampleRecipe),
        (R.SampleUse, R.ingredient, R.SampleIngredient),
        (R.SampleUse, R.unitText, Literal("g")),
        (R.SampleUse, R.evidence, R.SampleEvidence),
        (R.SampleEvidence, RDF.type, R.Evidence),
        (R.SampleEvidence, R.sourceId, Literal("source")),
        (R.SampleEvidence, R.quote, Literal("recorded fact")),
    ):
        data.add(triple)
    conforms, report, _ = validate_shapes(data, shacl_graph=model.shapes_graph())
    assert not conforms
    assert (None, SH.resultPath, R.unitText) in report


@pytest.mark.parametrize(
    "triple",
    [
        (R.RecipeVariant, OWL.equivalentClass, R.Dish),
        (R.RecipeVariant, OWL.imports, URIRef("https://example.org/remote.ttl")),
        (R.Rule, RDF.type, URIRef("http://www.w3.org/2003/11/swrl#Imp")),
    ],
)
def test_unsupported_owl_rules_and_remote_imports_are_visible(tmp_path, triple):
    with pytest.raises(ValueError, match="Unsupported|Remote"):
        edited_model(tmp_path, ontology_edit=lambda graph: graph.add(triple))


@pytest.mark.parametrize(
    "predicate,value",
    [
        (SH.js, Literal("fetch('https://example.org')")),
        (OWL.imports, URIRef("https://example.org/shape.ttl")),
    ],
)
def test_unsupported_shape_execution_is_rejected_before_validation(tmp_path, predicate, value):
    def edit(graph):
        graph.add((R.InputRecipeShape, predicate, value))

    with pytest.raises(ValueError, match="Unsupported"):
        edited_model(tmp_path, shapes_edit=edit)


def test_manifest_rdf_failure_does_not_load_an_old_yaml_fallback(monkeypatch, tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text(
        "format: rdf\nontology: missing.ttl\nshapes: missing.shacl.ttl\n", encoding="utf-8"
    )
    monkeypatch.setattr(domain_config.settings, "KNOWLEDGE_DOMAIN_FILE", str(path))
    with pytest.raises(FileNotFoundError):
        domain_config.get_domain_definition()
