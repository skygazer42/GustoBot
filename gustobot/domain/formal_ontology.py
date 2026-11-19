"""Compile a bounded local OWL/RDFS + SHACL model into native graph contracts.

OWL-RL derives the named class/property closure. SHACL defines integrity and
native storage constraints; domain/range axioms never substitute for validation.
Binding annotations below are explicit executable contracts, not LLM hints.
Storage query scopes cover forward native subproperties and the complete
IngredientUse reification path. Other property chains can run on retrieved RDF,
but cannot back a business query whose native projection would be incomplete.
Inverse query alternatives are limited to the explicitly projected reification pair.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from urllib.parse import unquote, urlparse

from owlrl import DeductiveClosure, OWLRL_Semantics
from rdflib import RDF, RDFS, Graph, Literal, Namespace, URIRef
from rdflib.compare import to_isomorphic
from rdflib.namespace import OWL, SH, XSD
from rdflib.term import Node

from gustobot.domain.knowledge import (
    Cardinality,
    DomainDefinition,
    EntityTypeDefinition,
    ExternalReference,
    LexiconEntry,
    OntologyRule,
    PropertyDefinition,
    RelationTypeDefinition,
    ScalarValue,
    SubgraphShape,
    UnitDefinition,
    VocabularySource,
)
from gustobot.domain.linking import CatalogRecord
from gustobot.domain.numeric import NumericProjectionSpec

B = Namespace("https://gustobot.org/ontology/binding#")


@dataclass(frozen=True)
class SemanticPropertyBinding:
    symbol: str
    label: str
    aliases: tuple[str, ...]
    anchor_type: str
    relation_types: tuple[str, ...]
    fields: tuple[str, ...]
    target_type: str | None
    answer_shape: URIRef
    semantic_relations: tuple[URIRef, ...] = ()


@dataclass(frozen=True)
class UnitSpec:
    symbol: str
    dimension: str
    scale: Decimal
    uri: URIRef
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class IdentitySpec:
    strategy: str
    key_fields: tuple[str, ...]
    prefix: str


@dataclass(frozen=True)
class NativeRelationBinding:
    symbol: str
    uri: URIRef
    source_types: tuple[str, ...]
    target_types: tuple[str, ...]
    reification_class: URIRef | None
    role: str | None
    owns_target: bool


@dataclass(frozen=True)
class FormalOntology:
    id: str
    version: str
    namespace: str
    fingerprint: str
    native_classes: Mapping[str, URIRef]
    native_relations: Mapping[str, NativeRelationBinding]
    property_bindings: Mapping[str, SemanticPropertyBinding]
    numeric_projections: Mapping[str, NumericProjectionSpec]
    _identities: Mapping[str, IdentitySpec]
    _fields: Mapping[str, URIRef]
    _units: Mapping[str, UnitSpec]
    _lexical_classes: Mapping[str, URIRef]
    _class_names: Mapping[URIRef, tuple[str, ...]]
    _ancestors: frozenset[tuple[URIRef, URIRef]]
    _ontology_triples: tuple[tuple[Node, Node, Node], ...]
    _asserted_triples: tuple[tuple[Node, Node, Node], ...]
    _shape_triples: tuple[tuple[Node, Node, Node], ...]
    _domain_json: str

    def __deepcopy__(self, memo):
        """All stored structures are immutable; sharing never exposes an RDF store."""
        return self

    def uri(self, local: str) -> URIRef:
        return URIRef(self.namespace + local)

    def ontology_graph(self) -> Graph:
        return _snapshot(self._ontology_triples)

    def asserted_ontology_graph(self) -> Graph:
        """Original local axioms, for derivation traces that cite real premises."""
        return _snapshot(self._asserted_triples)

    def shapes_graph(self) -> Graph:
        return _snapshot(self._shape_triples)

    def domain_definition(self) -> DomainDefinition:
        domain = DomainDefinition.model_validate_json(self._domain_json)
        domain._semantic_model = self
        return domain

    def identity_spec(self, entity_type: str) -> IdentitySpec:
        return self._identities[entity_type]

    def identity_keys(self, entity_type: str) -> tuple[str, ...]:
        return self.identity_spec(entity_type).key_fields

    def identity_id(self, entity_type: str, values: Mapping[str, ScalarValue]) -> str:
        spec = self.identity_spec(entity_type)
        parts: list[ScalarValue] = []
        for key in spec.key_fields:
            if key not in values:
                raise ValueError(f"Missing identity key {key} for {entity_type}")
            value = values[key]
            if key == "order":
                if type(value) is not int:
                    raise ValueError(f"Identity key order for {entity_type} must be an integer")
            elif not isinstance(value, str) or not value.strip():
                raise ValueError(f"Identity key {key} for {entity_type} must be nonempty text")
            if spec.strategy == "CanonicalName" and key == "name":
                value = _normalize(str(value))
            parts.append(value)
        encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return spec.prefix + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def property_binding(self, symbol: str) -> SemanticPropertyBinding:
        return self.property_bindings[symbol]

    @property
    def numeric_projection_version(self) -> str:
        if not self.numeric_projections:
            raise ValueError("The formal model declares no numeric projections")
        return next(iter(self.numeric_projections.values())).projection_version

    def field_uri(self, owner: str, field: str) -> URIRef:
        return self._fields[f"{owner}.{field}"]

    def classify_name(self, name: str, base_type: str = "Ingredient") -> URIRef | None:
        base = self.native_classes[base_type]
        candidate = self._lexical_classes.get(_normalize(name))
        if candidate is not None and (candidate == base or (candidate, base) in self._ancestors):
            return candidate
        return None

    def expand_names(self, mention: str, base_type: str = "Ingredient") -> tuple[str, ...]:
        selected = self.classify_name(mention, base_type)
        if selected is None:
            candidate = URIRef(mention) if ":" in mention else self.uri(mention)
            base = self.native_classes[base_type]
            if candidate == base or (candidate, base) in self._ancestors:
                selected = candidate
        if selected is None:
            return (mention,)
        names = {
            name
            for class_uri, class_names in self._class_names.items()
            if class_uri == selected or (class_uri, selected) in self._ancestors
            for name in class_names
        }
        return tuple(sorted(names))

    def unit_spec(self, name: str) -> UnitSpec | None:
        return self._units.get(_normalize(name))

    def linking_records(self) -> tuple[CatalogRecord, ...]:
        """Describe declared concepts, without consulting instance or source facts."""
        ontology = self.asserted_ontology_graph()
        records = []
        native_symbols = {uri: symbol for symbol, uri in self.native_classes.items()}
        for uri in sorted(set(self.native_classes.values()) | set(self._class_names)):
            records.append(
                CatalogRecord.create(
                    domain_id=self.id,
                    ontology_version=self.version,
                    ontology_fingerprint=self.fingerprint,
                    kind="concept",
                    ref_kind="class",
                    ref_id=str(uri),
                    object_type=native_symbols.get(uri, str(uri).removeprefix(self.namespace)),
                    label=_text(ontology, uri, RDFS.label),
                    aliases=self._class_names.get(uri, ()),
                    description=_text(ontology, uri, RDFS.comment, optional=True),
                )
            )
        for symbol, binding in sorted(self.property_bindings.items()):
            node = next(ontology.subjects(B.symbol, Literal(symbol)))
            description = json.dumps(
                {
                    "anchor": binding.anchor_type,
                    "target": binding.target_type,
                    "fields": binding.fields,
                    "relations": binding.relation_types,
                    "description": _text(ontology, node, RDFS.comment, optional=True),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            records.append(
                CatalogRecord.create(
                    domain_id=self.id,
                    ontology_version=self.version,
                    ontology_fingerprint=self.fingerprint,
                    kind="concept",
                    ref_kind="property",
                    ref_id=f"property:{symbol}",
                    object_type="SemanticProperty",
                    label=binding.label,
                    aliases=binding.aliases,
                    description=description,
                )
            )
        return tuple(sorted(records, key=lambda record: record.ref_id))


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _snapshot(triples) -> Graph:
    graph = Graph()
    for triple in triples:
        graph.add(triple)
    return graph


def _one(graph: Graph, subject, predicate, *, optional=False):
    values = list(graph.objects(subject, predicate))
    if not values and optional:
        return None
    if len(values) != 1:
        raise ValueError(f"Expected exactly one {predicate} on {subject}")
    return values[0]


def _text(graph: Graph, subject, predicate, *, optional=False) -> str:
    value = _one(graph, subject, predicate, optional=optional)
    if value is None:
        return ""
    if not isinstance(value, Literal) or not str(value).strip():
        raise ValueError(f"Expected nonempty literal {predicate} on {subject}")
    return str(value)


def _list(graph: Graph, subject, predicate) -> tuple:
    head = _one(graph, subject, predicate)
    try:
        return tuple(graph.items(head))
    except ValueError as exc:
        raise ValueError(f"Invalid RDF list {predicate} on {subject}") from exc


def _references(graph: Graph, subject) -> list[ExternalReference]:
    return [
        ExternalReference.model_validate(
            {
                "source": _text(graph, node, B.source),
                "uri": str(_one(graph, node, B.uri)),
                "kind": _text(graph, node, B.kind),
                "note": _text(graph, node, RDFS.comment, optional=True),
            }
        )
        for node in graph.objects(subject, B.externalReference)
    ]


_OWL_PREDICATES = {
    OWL.imports,
    OWL.versionInfo,
    OWL.versionIRI,
    OWL.inverseOf,
    OWL.propertyChainAxiom,
}
_OWL_TYPES = {
    OWL.Ontology,
    OWL.Class,
    OWL.ObjectProperty,
    OWL.DatatypeProperty,
    OWL.AnnotationProperty,
    OWL.NamedIndividual,
}
_BINDING_PREDICATES = {
    B.id,
    B.namespace,
    B.documentScope,
    B.interpretationNote,
    B.symbol,
    B.version,
    B.definitionUrl,
    B.sha256,
    B.terms,
    B.nativeSymbol,
    B.grain,
    B.identity,
    B.strategy,
    B.keyFields,
    B.prefix,
    B.externalReference,
    B.source,
    B.uri,
    B.kind,
    B.lexicalName,
    B.reificationClass,
    B.role,
    B.ownsTarget,
    B.alias,
    B.anchor,
    B.relation,
    B.fields,
    B.target,
    B.answerShape,
    B.nativeOwner,
    B.nativeField,
    B.ruleId,
    B.field,
    B.dimension,
    B.tickUnit,
    B.minimum,
    B.maximum,
    B.projectionVersion,
}
_SHACL_PREDICATES = {
    SH.targetClass,
    SH.property,
    SH.path,
    SH["class"],
    SH.minCount,
    SH.maxCount,
    SH.datatype,
    SH.minInclusive,
    SH.maxInclusive,
    SH.minLength,
    SH.description,
    SH.node,
    SH["or"],
    SH.lessThanOrEquals,
    SH.sparql,
    SH.message,
    SH.select,
}


def _check_supported(graph: Graph, *, shapes=False) -> None:
    for subject, predicate, obj in graph:
        if shapes and predicate == OWL.imports:
            raise ValueError("Unsupported SHACL imports; shapes must be self-contained")
        if str(predicate).startswith(str(OWL)) and predicate not in _OWL_PREDICATES:
            raise ValueError(f"Unsupported OWL axiom {predicate}")
        if predicate == RDF.type and str(obj).startswith(str(OWL)) and obj not in _OWL_TYPES:
            raise ValueError(f"Unsupported OWL construct {obj}")
        if any(
            str(term).startswith(
                ("http://www.w3.org/2003/11/swrl", "http://www.w3.org/2000/10/swap")
            )
            for term in (predicate, obj)
        ):
            raise ValueError("Unsupported rule language")
        if str(predicate).startswith(str(B)) and predicate not in _BINDING_PREDICATES:
            raise ValueError(f"Unsupported binding contract {predicate}")
        if str(predicate).startswith(str(SH)) and (
            not shapes or predicate not in _SHACL_PREDICATES
        ):
            raise ValueError(f"Unsupported SHACL construct {predicate}")
        if predicate in {
            RDFS.subClassOf,
            RDFS.subPropertyOf,
            RDFS.domain,
            RDFS.range,
            OWL.inverseOf,
        } and (not isinstance(subject, URIRef) or not isinstance(obj, URIRef)):
            raise ValueError(f"Unsupported anonymous OWL/RDFS expression {predicate}")
        if predicate == SH.path and not isinstance(obj, URIRef):
            raise ValueError("Unsupported complex SHACL path")
        if predicate == OWL.propertyChainAxiom:
            chain = tuple(graph.items(obj))
            if (
                not isinstance(subject, URIRef)
                or not 2 <= len(chain) <= 4
                or any(not isinstance(item, URIRef) for item in chain)
            ):
                raise ValueError("Unsupported property chain")
        if predicate == SH.select:
            _check_select(graph, subject, str(obj))


def _check_select(graph: Graph, subject, query: str) -> None:
    """Accept only the declared local uniqueness SELECT, not arbitrary SPARQL."""
    kind = _text(graph, subject, B.kind)
    relation = _one(graph, subject, B.relation)
    field = _text(graph, subject, B.field)
    namespace, separator, local = str(relation).rpartition("#")
    if (
        kind != "unique_relation_property"
        or not separator
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", local + field)
    ):
        raise ValueError("Unsupported SHACL SELECT constraint")
    expected = (
        f"PREFIX r: <{namespace}#> SELECT $this ?order WHERE {{ "
        f"$this r:{local} ?left, ?right . ?left r:{field} ?order . "
        f"?right r:{field} ?order . FILTER (?left != ?right) }}"
    )
    if " ".join(query.split()) != " ".join(expected.split()):
        raise ValueError(
            "Unsupported SHACL SELECT; only the declared uniqueness template is allowed"
        )


def _load_local_ontology(path: Path) -> Graph:
    graph = Graph().parse(path, format="turtle")
    _check_supported(graph)
    allowed = (path.parent / "schema-recipe-subset.ttl").resolve()
    for subject, imported in tuple(graph.subject_objects(OWL.imports)):
        parsed = urlparse(str(imported))
        if parsed.scheme != "file":
            raise ValueError(f"Remote ontology imports are not supported: {imported}")
        imported_path = Path(
            unquote(
                parsed.path.lstrip("/") if re.match(r"^/[A-Za-z]:", parsed.path) else parsed.path
            )
        ).resolve()
        if imported_path != allowed:
            raise ValueError(f"Unsupported local ontology import: {imported}")
        imported_graph = Graph().parse(allowed, format="turtle")
        _check_supported(imported_graph)
        if any(imported_graph.objects(None, OWL.imports)):
            raise ValueError("Unsupported nested ontology import")
        graph += imported_graph
        # The bundle identity must not depend on its installation directory.
        graph.remove((subject, OWL.imports, imported))
        graph.add((subject, OWL.imports, URIRef("urn:gustobot:schema-recipe-subset")))
    return graph


def _native_properties(
    shapes: Graph, owners: Mapping[str, URIRef | None]
) -> tuple[dict[str, dict[str, PropertyDefinition]], dict[str, URIRef]]:
    properties: dict[str, dict[str, PropertyDefinition]] = {owner: {} for owner in owners}
    fields: dict[str, URIRef] = {}
    datatypes = {
        XSD.string: "string",
        XSD.integer: "integer",
        XSD.decimal: "number",
        XSD.double: "number",
        XSD.boolean: "boolean",
    }
    for node in set(shapes.subjects(B.nativeField, None)):
        name = _text(shapes, node, B.nativeField)
        path = _one(shapes, node, SH.path)
        datatype = _one(shapes, node, SH.datatype)
        if datatype not in datatypes or not isinstance(path, URIRef):
            raise ValueError(f"Unsupported native property datatype/path {name}")
        minimum = _one(shapes, node, SH.minInclusive, optional=True)
        maximum = _one(shapes, node, SH.maxInclusive, optional=True)
        count = _one(shapes, node, SH.minCount, optional=True)
        definition = PropertyDefinition.model_validate(
            {
                "type": datatypes[datatype],
                "required": count is not None and int(count) > 0,
                "description": _text(shapes, node, SH.description, optional=True),
                "minimum": None if minimum is None else minimum.toPython(),
                "maximum": None if maximum is None else maximum.toPython(),
                "external_refs": _references(shapes, node),
            }
        )
        for owner_value in shapes.objects(node, B.nativeOwner):
            owner = str(owner_value)
            if owner not in owners or name in properties[owner]:
                raise ValueError(f"Unknown or duplicate native field {owner}.{name}")
            targets = {
                target
                for parent in shapes.subjects(SH.property, node)
                for target in shapes.objects(parent, SH.targetClass)
            }
            if owners[owner] is None or owners[owner] not in targets:
                raise ValueError(f"Native field shape {owner}.{name} needs an executable target")
            properties[owner][name] = definition.model_copy(deep=True)
            fields[f"{owner}.{name}"] = path
    return properties, fields


def _relation_contract(shapes: Graph, uri: URIRef, symbols: Mapping[URIRef, str]):
    sources, targets = set(), set()
    bounds: set[tuple[int, int | None]] = set()
    for prop in shapes.subjects(SH.path, uri):
        target = _one(shapes, prop, SH["class"], optional=True)
        if target not in symbols:
            continue
        for shape in shapes.subjects(SH.property, prop):
            for source in shapes.objects(shape, SH.targetClass):
                if isinstance(source, URIRef) and source in symbols:
                    sources.add(symbols[source])
                    targets.add(symbols[target])
                    low = _one(shapes, prop, SH.minCount, optional=True)
                    high = _one(shapes, prop, SH.maxCount, optional=True)
                    bounds.add(
                        (
                            0 if low is None else int(low),
                            None if high is None else int(high),
                        )
                    )
    if not sources or not targets or len(bounds) != 1:
        raise ValueError(
            f"Native relation {uri} needs an unambiguous SHACL endpoint/cardinality contract"
        )
    low, high = bounds.pop()
    return (
        tuple(sorted(sources)),
        tuple(sorted(targets)),
        Cardinality(minimum=low, maximum=high),
    )


def _native_symbols(graph: Graph, rdf_type: URIRef) -> dict[str, URIRef]:
    result = {}
    for uri in graph.subjects(RDF.type, rdf_type):
        if graph.value(uri, B.nativeSymbol) is None:
            continue
        symbol = _text(graph, uri, B.nativeSymbol)
        if not isinstance(uri, URIRef) or symbol in result:
            raise ValueError(f"Duplicate or anonymous native symbol {symbol}")
        result[symbol] = uri
    return result


def _check_projection_rules(
    logical: URIRef,
    selected: set[str],
    relation_uris: Mapping[str, URIRef],
    asserted: Graph,
    closure: Graph,
    namespace: str,
) -> None:
    """Reject derivation alternatives that a finite native edge scope cannot cover."""
    chains = [
        (owner, tuple(asserted.items(head)))
        for owner, head in asserted.subject_objects(OWL.propertyChainAxiom)
    ]
    inverses = tuple(asserted.subject_objects(OWL.inverseOf))
    dependencies = {logical}
    while True:
        expanded = (
            dependencies
            | {
                child
                for child, parent in closure.subject_objects(RDFS.subPropertyOf)
                if isinstance(child, URIRef) and parent in dependencies
            }
            | {
                URIRef(str(item))
                for owner, chain in chains
                if owner in dependencies
                for item in chain
            }
            | {
                right
                for left, right in inverses
                if left in dependencies and isinstance(right, URIRef)
            }
            | {
                left
                for left, right in inverses
                if right in dependencies and isinstance(left, URIRef)
            }
        )
        if expanded == dependencies:
            break
        dependencies = expanded
    relevant = [(owner, chain) for owner, chain in chains if owner in dependencies]
    builtin_inverse = {
        URIRef(namespace + "hasIngredientUse"),
        URIRef(namespace + "inRecipe"),
    }
    if any(
        {left, right} != builtin_inverse
        for left, right in inverses
        if left in dependencies or right in dependencies
    ):
        raise ValueError(
            f"Unsupported query projection: inverse alternatives for {logical} "
            "are outside the supported forward native projection"
        )
    builtin_owner = URIRef(namespace + "usesIngredient")
    builtin_chain = (
        URIRef(namespace + "hasIngredientUse"),
        URIRef(namespace + "ingredient"),
    )
    if any(owner != builtin_owner or chain != builtin_chain for owner, chain in relevant):
        raise ValueError(f"Unsupported query projection for property chain affecting {logical}")
    if relevant:
        all_uses = {
            name
            for name, native in relation_uris.items()
            if (native, B.reificationClass, URIRef(namespace + "IngredientUse")) in asserted
        }
        if not all_uses or not all_uses.issubset(selected):
            raise ValueError(
                f"Semantic relation {logical} has an incomplete forward native projection "
                "for its ingredient-use property chain"
            )


def _native_projections(
    logical_relations: tuple[URIRef, ...],
    relation_uris: Mapping[str, URIRef],
    asserted: Graph,
    closure: Graph,
    symbol: str,
    namespace: str,
) -> tuple[str, ...]:
    projections = set()
    for logical in logical_relations:
        if (logical, RDF.type, OWL.ObjectProperty) not in asserted:
            raise ValueError(
                f"Semantic relation {logical} in {symbol} must be a named object property"
            )
        selected = {
            name
            for name, native in relation_uris.items()
            if native == logical or (native, RDFS.subPropertyOf, logical) in closure
        }
        _check_projection_rules(logical, selected, relation_uris, asserted, closure, namespace)
        if not selected:
            raise ValueError(
                f"Semantic relation {logical} in {symbol} has no supported forward native projection"
            )
        projections.update(selected)
    return tuple(sorted(projections))


def load_formal_ontology(ontology_path: Path, shapes_path: Path) -> FormalOntology:
    """Load only local Turtle and reject semantics outside the supported fragment."""
    graph = _load_local_ontology(ontology_path.resolve(strict=True))
    shapes = Graph().parse(shapes_path.resolve(strict=True), format="turtle")
    _check_supported(shapes, shapes=True)
    metadata = list(graph.subjects(B.id, None))
    if len(metadata) != 1:
        raise ValueError("Exactly one ontology must declare a binding id")
    ontology = metadata[0]
    namespace = _text(graph, ontology, B.namespace)
    native_classes = _native_symbols(graph, OWL.Class)
    if not native_classes:
        raise ValueError("Native classes must be named OWL classes")
    class_symbols = {uri: symbol for symbol, uri in native_classes.items()}
    relation_uris = _native_symbols(graph, OWL.ObjectProperty)
    if set(native_classes).intersection(relation_uris):
        raise ValueError("Native class and relation symbols must be disjoint")
    owners = {
        **native_classes,
        **{
            symbol: _one(graph, uri, B.reificationClass, optional=True)
            for symbol, uri in relation_uris.items()
        },
    }
    properties, fields = _native_properties(shapes, owners)
    asserted_triples = tuple(graph)
    closure = _snapshot(asserted_triples)
    DeductiveClosure(OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False).expand(
        closure
    )
    identities = {}
    entities = {}
    strategy_names = {
        B.CanonicalName: "canonical_name",
        B.SourceScoped: "source_record_content",
        B.ParentPosition: "source_and_position",
    }
    for symbol, uri in native_classes.items():
        identity = _one(graph, uri, B.identity)
        strategy = _one(graph, identity, B.strategy)
        keys = tuple(str(item) for item in _list(graph, identity, B.keyFields))
        if (
            strategy not in strategy_names
            or not keys
            or len(keys) != len(set(keys))
            or set(keys) - {"name", "source_id", "parent_id", "order"}
        ):
            raise ValueError(f"Unsupported identity rule on {symbol}")
        identities[symbol] = IdentitySpec(
            str(strategy).removeprefix(str(B)), keys, _text(graph, identity, B.prefix)
        )
        entities[symbol] = EntityTypeDefinition.model_validate(
            {
                "label": _text(graph, uri, RDFS.label),
                "description": _text(graph, uri, RDFS.comment),
                "identity": strategy_names[strategy],
                "grain": _text(graph, uri, B.grain),
                "properties": properties[symbol],
                "external_refs": _references(graph, uri),
            }
        )
    relations, relation_bindings = {}, {}
    required: dict[str, list[str]] = {}
    for symbol, uri in relation_uris.items():
        sources, targets, cardinality = _relation_contract(shapes, uri, class_symbols)
        relations[symbol] = RelationTypeDefinition(
            source_types=list(sources),
            target_types=list(targets),
            description=_text(graph, uri, RDFS.comment),
            cardinality=cardinality,
            properties=properties[symbol],
            external_refs=_references(graph, uri),
        )
        reification = _one(graph, uri, B.reificationClass, optional=True)
        owns = _one(graph, uri, B.ownsTarget, optional=True)
        if owns is not None and (not isinstance(owns, Literal) or owns.datatype != XSD.boolean):
            raise ValueError(f"Invalid ownership contract on {symbol}")
        relation_bindings[symbol] = NativeRelationBinding(
            symbol,
            uri,
            sources,
            targets,
            reification,
            _text(graph, uri, B.role, optional=True) or None,
            False if owns is None else bool(owns.toPython()),
        )
        if cardinality.minimum > 0:
            for source in sources:
                required.setdefault(source, []).append(symbol)
    bindings, lexicon = {}, []
    all_symbols = {
        **class_symbols,
        **{uri: symbol for symbol, uri in relation_uris.items()},
    }
    for node in graph.subjects(RDF.type, B.SemanticProperty):
        symbol = _text(graph, node, B.symbol)
        anchor = all_symbols.get(_one(graph, node, B.anchor))
        target_node = _one(graph, node, B.target, optional=True)
        target = all_symbols.get(target_node)
        edge_nodes = tuple(graph.objects(node, B.relation))
        if any(not isinstance(item, URIRef) for item in edge_nodes):
            raise ValueError(f"Invalid native relation binding {symbol}")
        logical_relations = tuple(sorted(URIRef(str(item)) for item in edge_nodes))
        edges = _native_projections(
            logical_relations, relation_uris, graph, closure, symbol, namespace
        )
        field_names = tuple(str(item) for item in _list(graph, node, B.fields))
        answer = _one(graph, node, B.answerShape)
        if (
            symbol in bindings
            or anchor not in native_classes
            or (target_node is not None and target not in native_classes)
            or any(edge not in relations for edge in edges)
            or any(field not in fields for field in field_names)
            or (answer, RDF.type, SH.NodeShape) not in shapes
        ):
            raise ValueError(f"Invalid semantic property binding {symbol}")
        bindings[symbol] = SemanticPropertyBinding(
            symbol,
            _text(graph, node, RDFS.label),
            tuple(sorted(str(item) for item in graph.objects(node, B.alias))),
            anchor,
            edges,
            field_names,
            target,
            answer,
            logical_relations,
        )
        lexicon.append(
            LexiconEntry(
                terms=[bindings[symbol].label, *bindings[symbol].aliases],
                refs=list(dict.fromkeys([anchor, *edges, *field_names])),
            )
        )
    for symbol, entity in entities.items():
        lexicon.append(LexiconEntry(terms=[entity.label], refs=[symbol]))
    units, native_units = {}, {}
    for unit_node in graph.subjects(RDF.type, URIRef(namespace + "Unit")):
        if not isinstance(unit_node, URIRef):
            raise ValueError("Units must have named IRIs")  # noqa: TRY004 - invalid RDF contract
        symbol = _text(graph, unit_node, B.symbol)
        aliases = tuple(sorted(str(item) for item in graph.objects(unit_node, B.alias)))
        dimension = _text(graph, unit_node, URIRef(namespace + "dimension"))
        scale = Decimal(_text(graph, unit_node, URIRef(namespace + "scale")))
        if not scale.is_finite() or scale <= 0:
            raise ValueError(f"Invalid unit scale {symbol}")
        spec = UnitSpec(symbol, dimension, scale, unit_node, aliases)
        native_units[symbol] = UnitDefinition.model_validate(
            {"dimension": dimension, "aliases": list(aliases)}
        )
        for alias in (symbol, *aliases):
            normalized = _normalize(alias)
            if normalized in units:
                raise ValueError(f"Ambiguous unit alias {alias}")
            units[normalized] = spec
    projections = {}
    for node in graph.subjects(RDF.type, B.NumericProjection):
        dimension = _text(graph, node, B.dimension)
        tick_unit = _text(graph, node, B.tickUnit)
        unit = units.get(_normalize(tick_unit))
        if dimension in projections or unit is None or unit.dimension != dimension:
            raise ValueError(f"Invalid numeric projection for {dimension}")
        projections[dimension] = NumericProjectionSpec(
            dimension=dimension,
            tick_unit=tick_unit,
            minimum=int(_one(graph, node, B.minimum)),
            maximum=int(_one(graph, node, B.maximum)),
            projection_version=_text(graph, node, B.projectionVersion),
        )
    if len({spec.projection_version for spec in projections.values()}) > 1:
        raise ValueError("Numeric projections must share a projection version")
    vocabularies = {}
    for node in graph.subjects(RDF.type, B.Vocabulary):
        vocabularies[_text(graph, node, B.symbol)] = VocabularySource(
            namespace=_text(graph, node, B.namespace),
            version=_text(graph, node, B.version),
            definition_url=_text(graph, node, B.definitionUrl),
            sha256=_text(graph, node, B.sha256),
            terms=[str(item) for item in _list(graph, node, B.terms)],
        )
    rules = [
        OntologyRule.model_validate(
            {
                "id": _text(shapes, node, B.ruleId),
                "kind": _text(shapes, node, B.kind),
                "relation": all_symbols[_one(shapes, node, B.relation)],
                "property": _text(shapes, node, B.field),
            }
        )
        for node in shapes.subjects(SH.select, None)
    ]
    domain = DomainDefinition(
        id=_text(graph, ontology, B.id),
        version=_text(graph, ontology, OWL.versionInfo),
        name=_text(graph, ontology, RDFS.label),
        description=_text(graph, ontology, RDFS.comment),
        entity_types=entities,
        relation_types=relations,
        lexicon=lexicon,
        units=native_units,
        subgraph_shapes={
            key: SubgraphShape(required_edges=value) for key, value in required.items()
        },
        rules=rules,
        document_scope=_text(graph, ontology, B.documentScope),
        interpretation_notes=sorted(
            str(item) for item in graph.objects(ontology, B.interpretationNote)
        ),
        vocabularies=vocabularies,
    )
    fingerprint = hashlib.sha256(
        f"{to_isomorphic(graph).graph_digest()}:{to_isomorphic(shapes).graph_digest()}".encode()
    ).hexdigest()
    class_names: dict[URIRef, tuple[str, ...]] = {}
    lexical_classes: dict[str, URIRef] = {}
    for lexical_node in set(graph.subjects(B.lexicalName, None)):
        if not isinstance(lexical_node, URIRef) or (lexical_node, RDF.type, OWL.Class) not in graph:
            raise ValueError("Lexical classes must be named OWL classes")
        names = tuple(sorted(str(item) for item in graph.objects(lexical_node, B.lexicalName)))
        class_names[lexical_node] = names
        for name in names:
            normalized = _normalize(name)
            if normalized in lexical_classes and lexical_classes[normalized] != lexical_node:
                raise ValueError(f"Ambiguous lexical class name {name}")
            lexical_classes[normalized] = lexical_node
    ancestors = frozenset(
        (child, parent)
        for child, parent in closure.subject_objects(RDFS.subClassOf)
        if isinstance(child, URIRef) and isinstance(parent, URIRef)
    )
    return FormalOntology(
        domain.id,
        domain.version,
        namespace,
        fingerprint,
        MappingProxyType(native_classes),
        MappingProxyType(relation_bindings),
        MappingProxyType(bindings),
        MappingProxyType(projections),
        MappingProxyType(identities),
        MappingProxyType(fields),
        MappingProxyType(units),
        MappingProxyType(lexical_classes),
        MappingProxyType(class_names),
        ancestors,
        tuple(closure),
        asserted_triples,
        tuple(shapes),
        domain.model_dump_json(),
    )
