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
        """Reject duplicate mapping keys before using PyYAML's normal constructor."""
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate YAML key in domain definition")
        return super().construct_mapping(node, deep=deep)


class _RdfManifest(BaseModel):
    """Paths to the ontology and SHACL graph named by an RDF domain profile."""

    model_config = ConfigDict(extra="forbid", strict=True)
    format: str
    ontology: str
    shapes: str


@lru_cache(maxsize=16)
def _load_domain_definition(path: Path) -> DomainDefinition:
    """Load, compile, and validate one YAML or RDF domain profile."""
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("Domain definitions must use YAML profiles (.yaml or .yml)")
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid domain YAML: {path}") from exc
    if isinstance(payload, dict) and "format" in payload:
        # RDF 清单同时加载本体语义和 SHACL 数据约束，不只是读取名称配置。
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
    # 复用编译缓存但返回深拷贝，避免一个请求的可变模型改动污染其他请求。
    return _load_domain_definition(path.resolve(strict=True)).model_copy(deep=True)
