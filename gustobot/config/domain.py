"""Load explicit YAML domains or a manifest of local executable RDF resources."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from gustobot.config.settings import settings
from gustobot.domain.knowledge import DomainDefinition, KnowledgeGraph, validate_graph

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys instead of silently changing a published definition."""

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate YAML key in domain definition")
        return super().construct_mapping(node, deep=deep)


class _RdfManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format: str
    ontology: str
    shapes: str


@lru_cache(maxsize=16)
def _load_domain_definition(path: Path) -> DomainDefinition:
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("Domain definitions must use YAML profiles (.yaml or .yml)")
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid domain YAML: {path}") from exc
    if isinstance(payload, dict) and "format" in payload:
        manifest = _RdfManifest.model_validate(payload)
        if manifest.format != "rdf":
            raise ValueError(f"Unsupported domain format: {manifest.format}")
        from gustobot.domain.formal_ontology import load_formal_ontology

        definition = load_formal_ontology(
            (path.parent / manifest.ontology).resolve(strict=True),
            (path.parent / manifest.shapes).resolve(strict=True),
        ).domain_definition()
    else:
        definition = DomainDefinition.model_validate(payload)
    validate_graph(definition, KnowledgeGraph(entities=[], relations=[], sources=[]))
    return definition


def get_domain_definition() -> DomainDefinition:
    """Resolve repository-relative configuration and isolate callers' mutable models."""
    path = Path(settings.KNOWLEDGE_DOMAIN_FILE)
    if not path.is_absolute():
        path = REPOSITORY_ROOT / path
    return _load_domain_definition(path.resolve(strict=True)).model_copy(deep=True)
