"""Review graph candidates against the authoritative stored source version."""

import asyncio

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, ConfigDict

from gustobot.application.services.ontology_service import OntologyService
from gustobot.domain.knowledge import DomainDefinition, KnowledgeGraph, SourceDocument
from gustobot.infrastructure.core.database import session_scope
from gustobot.infrastructure.knowledge.graph_store import (
    FactResult,
    GraphWriteResult,
    Neo4jGraphStore,
)
from gustobot.infrastructure.knowledge.semantic_runtime import SemanticValidationError
from gustobot.infrastructure.persistence.crud.knowledge import KnowledgeRepository


class DraftValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid: bool
    errors: list[str]


class GraphDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    graph: KnowledgeGraph
    validation: DraftValidation


class SourceConflict(ValueError):
    """The selected source cannot be edited in its present state."""


class SourceNotFound(LookupError):
    """The requested source version is absent in the configured domain."""


class InvalidGraph(ValueError):
    """The source selection or proposed graph failed a review input constraint."""


class OntologyAdminService:
    def __init__(self, domain: DomainDefinition, *, session_factory=session_scope):
        self.domain = domain
        self.session_factory = session_factory
        self.ontology = OntologyService(domain)

    def _source(self, source_id: str, version: str, *, document: bool) -> SourceDocument:
        with self.session_factory() as session:
            source = KnowledgeRepository(session).get_source(self.domain.id, source_id, version)
            if source is None:
                raise SourceNotFound("资料来源版本不存在")
            if source.ontology_version != self.domain.version:
                raise SourceConflict("资料的本体版本与当前本体不一致，请先重新入库资料")
            if document:
                if source.status == "withdrawn":
                    raise SourceConflict("已撤回资料不能抽取或写入图谱")
                if (
                    source.source_metadata is None
                    or source.source_metadata.get("kind") != "document"
                ):
                    raise SourceConflict("图谱核对仅支持已登记的文档资料")
            uri: str | None = source.uri
            if (
                not document
                and source.source_metadata is not None
                and source.source_metadata.get("kind") == "recipe"
                and uri == source.source_id
            ):
                # Recipe ingestion stores a missing URI as its ID only in MySQL.
                uri = None
            return SourceDocument(id=source.source_id, text=source.text, uri=uri)

    @staticmethod
    def _check_source(graph: KnowledgeGraph, source: SourceDocument) -> None:
        if graph.sources != [source]:
            raise InvalidGraph("图谱来源的 ID、原文和 URI 必须与所选资料版本完全一致")
        if any(
            reference.source_id != source.id
            for collection in (graph.entities, graph.relations)
            for fact in collection
            for reference in fact.evidence
        ):
            raise InvalidGraph("所有实体和关系的证据必须引用所选资料来源")

    def _draft(self, graph: KnowledgeGraph) -> GraphDraft:
        try:
            bound = self.ontology._validate_candidate(graph)
        except SemanticValidationError as error:
            errors = [issue.message for issue in error.report.issues]
        except ValueError as error:
            errors = [str(error)]
        else:
            return GraphDraft(graph=bound, validation=DraftValidation(valid=True, errors=[]))
        return GraphDraft(graph=graph, validation=DraftValidation(valid=False, errors=errors))

    async def extract(self, source_id: str, version: str, model: BaseChatModel) -> GraphDraft:
        source = await asyncio.to_thread(self._source, source_id, version, document=True)
        if len(source.text) > 40000:
            raise InvalidGraph("图谱抽取最多支持 40000 字符，请拆分文档后重新上传；原文不会被截断")
        graph = await OntologyService(self.domain, model=model).extract_candidate([source])
        return await asyncio.to_thread(self._draft, graph)

    async def validate(self, source_id: str, version: str, graph: KnowledgeGraph) -> GraphDraft:
        source = await asyncio.to_thread(self._source, source_id, version, document=True)
        self._check_source(graph, source)
        return await asyncio.to_thread(self._draft, graph)

    async def insert(
        self, source_id: str, version: str, graph: KnowledgeGraph, store: Neo4jGraphStore
    ) -> GraphWriteResult:
        source = await asyncio.to_thread(self._source, source_id, version, document=True)
        self._check_source(graph, source)
        try:
            return await OntologyService(self.domain, graph_store=store).insert(graph)
        except SemanticValidationError:
            raise
        except ValueError as error:
            # The existing graph store exposes immutable-source conflicts as ValueError.
            if str(error).startswith("Source identity is immutable;"):
                raise SourceConflict(str(error)) from error
            raise InvalidGraph(str(error)) from error

    async def source_facts(
        self, source_id: str, version: str, store: Neo4jGraphStore, *, limit: int
    ) -> FactResult:
        source = await asyncio.to_thread(self._source, source_id, version, document=False)
        return await store.source_facts(source, version=version, limit=limit)
