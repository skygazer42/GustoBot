"""Load the selected knowledge domain from an explicit JSON file."""

from functools import lru_cache
from pathlib import Path

from gustobot.config.settings import settings
from gustobot.domain.knowledge import DomainDefinition, KnowledgeGraph, validate_graph


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=16)
def _load_domain_definition(path: Path) -> DomainDefinition:
    definition = DomainDefinition.model_validate_json(path.read_text(encoding="utf-8"))
    validate_graph(definition, KnowledgeGraph(entities=[], relations=[], sources=[]))
    return definition


def get_domain_definition() -> DomainDefinition:
    """Resolve repository-relative configuration and isolate callers' mutable models."""
    path = Path(settings.KNOWLEDGE_DOMAIN_FILE)
    if not path.is_absolute():
        path = REPOSITORY_ROOT / path
    return _load_domain_definition(path.resolve(strict=True)).model_copy(deep=True)
