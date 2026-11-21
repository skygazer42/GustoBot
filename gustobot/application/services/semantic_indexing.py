"""Build immutable candidate snapshots, then publish through a short MySQL transaction."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeVar
from uuid import uuid4

from loguru import logger
from sqlalchemy.orm import Session

from gustobot.domain.knowledge import DomainDefinition
from gustobot.domain.linking import (
    BuildIndexReceipt,
    BuildIndexRequest,
    CatalogRecord,
    GraphRevision,
    IndexGeneration,
    IndexPublicationStatus,
    IndexScope,
    catalog_checksum,
)
from gustobot.infrastructure.core.database import session_scope
from gustobot.infrastructure.persistence.crud.semantic_index import (
    BuildLeaseConflict,
    PublicationConflict,
    SemanticIndexRepository,
)
from gustobot.infrastructure.persistence.db.models.knowledge import _utc_now

if TYPE_CHECKING:
    from gustobot.infrastructure.knowledge.embeddings import OpenAICompatibleEmbeddings
    from gustobot.infrastructure.knowledge.graph_store import Neo4jGraphStore
    from gustobot.infrastructure.knowledge.semantic_index import SemanticCandidateStore

_Result = TypeVar("_Result")


class _CatalogChanged(RuntimeError):
    """Signal that the graph changed while a candidate catalog was exported."""


@dataclass
class _BuildProgress:
    """Mutable counters for the current embedding and index-write phase."""

    embedded: int
    reused: int = 0
    written: int = 0
    stage: str = "catalog export"


def _approved_calibration(path: Path) -> tuple[dict, str]:
    """The evaluator validates embedded real-provider evidence, not a caller flag."""
    from scripts.evaluate_knowledge import validate_approved_calibration_report

    path = path.resolve(strict=True)
    if path.name == ".env" or path.name.startswith(".env."):
        raise ValueError("A dotenv file cannot be a calibration report")
    raw = path.read_bytes()
    report = validate_approved_calibration_report(json.loads(raw))
    return report, hashlib.sha256(raw).hexdigest()


class SemanticIndexingService:
    """External I/O never holds an application database transaction open."""

    def __init__(
        self,
        domain: DomainDefinition,
        *,
        graph_store: Neo4jGraphStore | Callable[[], Neo4jGraphStore],
        candidate_store: SemanticCandidateStore | Callable[[], SemanticCandidateStore],
        embedder: OpenAICompatibleEmbeddings | Callable[[], OpenAICompatibleEmbeddings],
        session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
        owner: str | None = None,
        lease_seconds: float = 120,
        clock: Callable[[], datetime] = _utc_now,
        embedding_fingerprint: str | None = None,
    ):
        if domain.semantic_model is None:
            raise ValueError("Semantic indexing requires a compiled formal ontology")
        self.formal = domain.semantic_model
        if lease_seconds <= 0:
            raise ValueError("Build lease duration must be positive")
        self.domain, self.graph_store = domain, graph_store
        self.candidate_store, self.embedder = candidate_store, embedder
        self.session_factory = session_factory
        self.owner = uuid4().hex if owner is None else owner
        self.lease_seconds, self.clock = lease_seconds, clock
        if embedding_fingerprint is None:
            if callable(candidate_store):
                raise ValueError("Lazy candidate stores require an explicit embedding fingerprint")
            embedding_fingerprint = candidate_store.embedding_fingerprint
        self.embedding_fingerprint = embedding_fingerprint

    async def _graph(self) -> Neo4jGraphStore:
        source = self.graph_store
        if callable(source):
            graph = await asyncio.to_thread(source)
            self.graph_store = graph
            return graph
        return source

    async def _candidates(self) -> SemanticCandidateStore:
        source = self.candidate_store
        if callable(source):
            store = await asyncio.to_thread(source)
            self.candidate_store = store
            return store
        return source

    async def _embedder(self) -> OpenAICompatibleEmbeddings:
        source = self.embedder
        if callable(source):
            embedder = await asyncio.to_thread(source)
            self.embedder = embedder
            return embedder
        return source

    def scope(self, kind: Literal["concept", "entity"]) -> IndexScope:
        """Return the current immutable ontology and embedding scope for a kind."""
        return IndexScope(
            domain_id=self.domain.id,
            ontology_version=self.domain.version,
            ontology_fingerprint=self.formal.fingerprint,
            embedding_fingerprint=self.embedding_fingerprint,
            kind=kind,
        )

    def _transaction(self, operation: Callable[[SemanticIndexRepository], _Result]) -> _Result:
        with self.session_factory() as session:
            return operation(SemanticIndexRepository(session))

    def _generation(self, generation_id: str) -> IndexGeneration:
        generation = self._transaction(lambda repo: repo.get_generation(generation_id))
        if generation is None:
            raise LookupError("Semantic generation no longer exists")
        return generation

    async def graph_revision(self) -> GraphRevision:
        """Read the authoritative graph revision used to validate entity indexes."""
        return await (await self._graph()).graph_revision()

    def _check_scope(self, scope: IndexScope) -> None:
        if scope != self.scope(scope.kind):
            raise ValueError("Build scope must match the current formal model and embedding space")

    async def _revision(self, scope: IndexScope) -> GraphRevision:
        revision = await self.graph_revision()
        if (
            revision.domain_id,
            revision.ontology_version,
            revision.ontology_fingerprint,
        ) != (
            scope.domain_id,
            scope.ontology_version,
            scope.ontology_fingerprint,
        ):
            raise ValueError("Graph revision belongs to a different formal scope")
        return revision

    def _renew(self, generation_id: str) -> None:
        self._transaction(
            lambda repo: repo.renew_lease(
                generation_id,
                owner=self.owner,
                now=self.clock(),
                lease_seconds=self.lease_seconds,
            )
        )

    @staticmethod
    def _receipt(generation: IndexGeneration) -> BuildIndexReceipt:
        return BuildIndexReceipt(
            generation_id=generation.generation_id,
            status=generation.status,
            graph_revision=generation.graph_revision,
            exported=generation.expected_count,
            embedded=generation.embedded,
            reused=generation.reused,
            error=generation.error,
        )

    async def _records(
        self,
        scope: IndexScope,
        revision: int | None,
        generation_id: str,
        batch_size: int,
    ) -> list[CatalogRecord]:
        """Export and validate a complete catalog at the requested graph revision."""
        if scope.kind == "concept":
            records = list(self.formal.linking_records())
        else:
            graph = await self._graph()
            records, after_id = [], None
            while True:
                await asyncio.to_thread(self._renew, generation_id)
                page = await graph.export_linking_records(after_id=after_id, limit=batch_size)
                if page.observed_revision != revision:
                    raise _CatalogChanged("Graph revision changed during catalog export")
                if after_id is not None and any(item.ref_id <= after_id for item in page.records):
                    raise ValueError("Catalog keyset page repeated or regressed an identity")
                records.extend(page.records)
                if page.next_after_id is None:
                    break
                if (
                    not page.records
                    or page.next_after_id != page.records[-1].ref_id
                    or (after_id is not None and page.next_after_id <= after_id)
                ):
                    raise ValueError("Catalog keyset cursor did not advance")
                after_id = page.next_after_id
        validated = []
        for item in records:
            item = CatalogRecord.model_validate(item.model_dump())
            scope.validate_record(item)
            if item.graph_revision != revision:
                raise _CatalogChanged("Catalog row belongs to a different graph revision")
            validated.append(item)
        catalog_checksum(validated)  # Also rejects duplicate actual record identities.
        return validated

    async def _publish(
        self, generation: IndexGeneration, request: BuildIndexRequest
    ) -> IndexGeneration:
        """Publish only after rechecking generation ownership and expected active pointer."""
        # 构建期间事实图可能更新；实体索引只能发布到它实际导出的那个图版本。
        if request.scope.kind == "entity":
            observed = await self._revision(request.scope)
            if observed.state != "ready" or observed.revision != generation.graph_revision:
                raise _CatalogChanged("Graph revision changed before publication")
        try:
            await asyncio.to_thread(
                self._transaction,
                lambda repo: repo.publish(
                    generation.generation_id,
                    expected_active_generation=request.expected_active_generation,
                ),
            )
        except Exception:
            # 断线可能发生在 MySQL 已提交之后；先回读生效指针，不能直接判定发布失败。
            pointer = await asyncio.to_thread(
                self._transaction, lambda repo: repo.publication_status(request.scope)
            )
            if pointer.generation_id != generation.generation_id:
                raise
        return await asyncio.to_thread(self._generation, generation.generation_id)

    def _save_progress(
        self,
        generation_id: str,
        expected_count: int,
        checksum: str,
        progress: _BuildProgress,
    ) -> None:
        self._transaction(
            lambda repo: repo.update_progress(
                generation_id,
                expected_count=expected_count,
                written_count=progress.written,
                checksum=checksum,
                embedded=progress.embedded,
                reused=progress.reused,
                owner=self.owner,
                now=self.clock(),
            )
        )

    async def _write_candidates(
        self,
        generation: IndexGeneration,
        request: BuildIndexRequest,
        records: list[CatalogRecord],
        checksum: str,
        progress: _BuildProgress,
    ) -> None:
        """Reuse or create scoped vectors, write batches, and persist build progress."""
        await asyncio.to_thread(
            self._save_progress,
            generation.generation_id,
            len(records),
            checksum,
            progress,
        )
        candidates = await self._candidates()
        vectors_by_hash: dict[str, list[float]] = {}
        for start in range(0, len(records), request.batch_size):
            await asyncio.to_thread(self._renew, generation.generation_id)
            batch = records[start : start + request.batch_size]
            progress.stage = "vector reuse"
            text_hashes = list(dict.fromkeys(item.text_hash for item in batch))
            vectors_by_hash.update(
                await asyncio.to_thread(candidates.reusable_vectors, request.scope, text_hashes)
            )
            texts_to_embed = {
                item.text_hash: item.text for item in batch if item.text_hash not in vectors_by_hash
            }
            if texts_to_embed:
                progress.stage = "embedding"
                embedded_vectors = await (await self._embedder()).aembed_documents(
                    list(texts_to_embed.values())
                )
                if len(embedded_vectors) != len(texts_to_embed) or any(
                    not vector or any(not math.isfinite(value) for value in vector)
                    for vector in embedded_vectors
                ):
                    raise ValueError("Embedding response has invalid counts or values")
                vectors_by_hash.update(zip(texts_to_embed, embedded_vectors))
                progress.embedded += len(embedded_vectors)
                # Provider cost survives a subsequent candidate write failure.
                await asyncio.to_thread(
                    self._save_progress,
                    generation.generation_id,
                    len(records),
                    checksum,
                    progress,
                )
            progress.reused += len(batch) - len(texts_to_embed)
            await asyncio.to_thread(self._renew, generation.generation_id)
            progress.stage = "candidate write"
            await asyncio.to_thread(
                candidates.upsert,
                generation.generation_id,
                batch,
                [vectors_by_hash[item.text_hash] for item in batch],
            )
            progress.written += len(batch)
            await asyncio.to_thread(
                self._save_progress,
                generation.generation_id,
                len(records),
                checksum,
                progress,
            )

    async def _verify_and_mark_ready(
        self,
        generation: IndexGeneration,
        scope: IndexScope,
        expected_count: int,
        checksum: str,
        progress: _BuildProgress,
    ) -> IndexGeneration:
        """Verify vector count and checksum before marking a build publishable."""
        await asyncio.to_thread(self._renew, generation.generation_id)
        progress.stage = "generation verification"
        candidates = await self._candidates()
        verification = await asyncio.to_thread(
            candidates.verify_generation,
            generation.generation_id,
            expected_count=expected_count,
            expected_checksum=checksum,
        )
        if (
            not verification.valid
            or verification.count != expected_count
            or verification.checksum != checksum
        ):
            raise ValueError("Actual candidate count or checksum failed verification")
        if scope.kind == "entity":
            current = await self._revision(scope)
            if current.state != "ready" or current.revision != generation.graph_revision:
                raise _CatalogChanged("Graph revision changed during index construction")
        return await asyncio.to_thread(
            self._transaction,
            lambda repo: repo.mark_ready(
                generation.generation_id,
                expected_count=expected_count,
                written_count=verification.count,
                checksum=checksum,
                owner=self.owner,
                now=self.clock(),
            ),
        )

    async def build(self, request: BuildIndexRequest) -> BuildIndexReceipt:
        """Build a candidate generation and optionally publish its completed snapshot."""
        # 新索引写入独立代次，完成校验后才切换生效指针，在线查询不读取半成品。
        self._check_scope(request.scope)
        revision = None
        if request.scope.kind == "entity":
            observed = await self._revision(request.scope)
            if observed.state != "ready":
                raise RuntimeError("Entity candidate scope is not initialized and ready")
            revision = observed.revision
        generation = await asyncio.to_thread(
            self._transaction,
            lambda repo: repo.claim_build(
                request.scope,
                graph_revision=revision,
                owner=self.owner,
                now=self.clock(),
                lease_seconds=self.lease_seconds,
            ),
        )
        if generation.status == "active":
            return self._receipt(generation)
        progress = _BuildProgress(embedded=generation.embedded)
        try:
            if generation.status != "ready":
                records = await self._records(
                    request.scope,
                    revision,
                    generation.generation_id,
                    request.batch_size,
                )
                checksum = catalog_checksum(records)
                if generation.checksum and generation.checksum != checksum:
                    raise ValueError("A resumed generation cannot change its original catalog")
                await self._write_candidates(generation, request, records, checksum, progress)
                generation = await self._verify_and_mark_ready(
                    generation, request.scope, len(records), checksum, progress
                )
            if request.publish:
                progress.stage = "publication"
                generation = await self._publish(generation, request)
            return self._receipt(generation)
        except asyncio.CancelledError:
            try:
                await asyncio.to_thread(
                    self._outcome,
                    generation.generation_id,
                    status="failed",
                    error="cancelled",
                )
            except BuildLeaseConflict:
                logger.warning(
                    "Cancelled worker no longer owns candidate generation {}",
                    generation.generation_id,
                )
            raise
        except (PublicationConflict, _CatalogChanged) as error:
            return self._receipt(
                await asyncio.to_thread(
                    self._outcome,
                    generation.generation_id,
                    status="superseded",
                    error=str(error),
                )
            )
        except Exception as error:  # noqa: BLE001
            # Provider messages can contain request text or credentials. Persist
            # only the operation and exception type.
            reason = f"{progress.stage}: {type(error).__name__}"
            if isinstance(error, BuildLeaseConflict):
                reason = "build lease expired or changed owner"
            logger.error(
                "Candidate generation {} failed at {} ({})",
                generation.generation_id,
                progress.stage,
                type(error).__name__,
            )
            return self._receipt(
                await asyncio.to_thread(
                    self._outcome,
                    generation.generation_id,
                    status="failed",
                    error=reason,
                )
            )

    def _outcome(
        self, generation_id: str, *, status: Literal["failed", "superseded"], error: str
    ) -> IndexGeneration:
        """Persist a failed or superseded generation while preserving its diagnostic."""
        current = self._generation(generation_id)
        if current.status == "active":
            return current
        # Once ready, the build lease has been released. A stale build owner may
        # never overwrite another worker's resumed building generation.
        owner = self.owner if current.status == "building" else None
        return self._transaction(
            lambda repo: repo.update_outcome(generation_id, status=status, error=error, owner=owner)
        )

    async def status(self, scope: IndexScope) -> IndexPublicationStatus:
        """Return publication state, including graph staleness for entity indexes."""
        self._check_scope(scope)
        publication: IndexPublicationStatus = await asyncio.to_thread(
            self._transaction, lambda repo: repo.publication_status(scope)
        )
        if scope.kind == "concept":
            return publication
        revision = await self._revision(scope)
        if revision.state != "ready":
            return publication.model_copy(update={"status": "uninitialized"})
        if (
            publication.generation_id is not None
            and publication.graph_revision != revision.revision
        ):
            return publication.model_copy(update={"status": "stale"})
        return publication

    async def bootstrap(self, *, audit_only: bool = True):
        """Initialize or audit the graph revision scope before entity indexing."""
        return await (await self._graph()).bootstrap_graph_scope(audit_only=audit_only)

    async def calibrate(
        self,
        generation_id: str,
        report_path: Path,
        *,
        expected_active_generation: str | None = None,
    ) -> IndexPublicationStatus:
        """Validate an approved evaluation report and publish its calibrated policy."""
        report, report_hash = await asyncio.to_thread(_approved_calibration, report_path)
        scope = IndexScope.model_validate(report["scope"])
        self._check_scope(scope)
        if report["generation_id"] != generation_id:
            raise ValueError("Calibration report refers to a different candidate generation")
        generation = await asyncio.to_thread(self._generation, generation_id)
        if generation.scope != scope or generation.graph_revision != report["graph_revision"]:
            raise ValueError(
                "Calibration report model scope or graph revision differs from the generation"
            )
        if scope.kind == "entity":
            current = await self._revision(scope)
            if current.state != "ready" or current.revision != generation.graph_revision:
                raise PublicationConflict("Graph revision changed before calibration attachment")
        policy = dict(report["calibration"]["policy"]) | {
            "dataset_hash": report["calibration"]["dataset_hash"]
        }
        expected = (
            generation_id if expected_active_generation is None else expected_active_generation
        )
        return await asyncio.to_thread(
            self._transaction,
            lambda repo: repo.attach_calibration(
                scope,
                generation_id,
                expected_active_generation=expected,
                graph_revision=generation.graph_revision,
                calibration_id=report_hash,
                policy=policy,
            ),
        )

    async def retire(self, generation_id: str) -> None:
        """Retire a non-active generation and then remove its vector collection."""
        await asyncio.to_thread(self._transaction, lambda repo: repo.retire(generation_id))
        await asyncio.to_thread((await self._candidates()).delete_generation, generation_id)
