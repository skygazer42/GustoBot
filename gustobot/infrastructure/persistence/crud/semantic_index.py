"""Flush-only metadata operations; callers own commit and rollback boundaries."""

import math
import re
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from gustobot.domain.linking import (
    IndexGeneration,
    IndexPublicationStatus,
    IndexScope,
    digest,
)
from gustobot.infrastructure.persistence.db.models.knowledge import _utc_now
from gustobot.infrastructure.persistence.db.models.semantic_index import (
    SemanticIndexGeneration,
    SemanticIndexPublication,
)


class PublicationConflict(RuntimeError):
    """The expected pointer or graph revision is no longer current."""


class BuildLeaseConflict(RuntimeError):
    """Another worker owns the scope, or this worker's lease expired."""


def _scope_key(scope: IndexScope) -> str:
    return digest(scope.model_dump(exclude={"ontology_version"}))


def _validate_policy(calibration_id: str | None, policy: dict[str, Any]) -> None:
    """Require publication thresholds and provenance to match calibration rules."""
    if not policy and calibration_id is None:
        return
    if calibration_id is None or not calibration_id.strip() or len(calibration_id) > 128:
        raise ValueError("A published selection policy requires a valid calibration ID")
    if set(policy) != {"min_cosine", "margin", "dataset_hash"}:
        raise ValueError("Selection policy requires only calibrated threshold and dataset metadata")
    for key, minimum, maximum in (("min_cosine", -1, 1), ("margin", 0, 2)):
        value = policy[key]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not minimum <= value <= maximum
        ):
            raise ValueError("Selection policy threshold is outside its calibrated metric range")
    if (
        not isinstance(policy["dataset_hash"], str)
        or re.fullmatch(r"[0-9a-f]{64}", policy["dataset_hash"]) is None
    ):
        raise ValueError("Selection policy requires a verified dataset hash")


def _generation(row: SemanticIndexGeneration) -> IndexGeneration:
    return IndexGeneration(
        generation_id=row.generation_id,
        scope=IndexScope.model_validate(row.scope_json),
        graph_revision=row.graph_revision,
        status=row.status,
        expected_count=row.expected_count,
        written_count=row.written_count,
        embedded=row.embedded,
        reused=row.reused,
        checksum=row.checksum,
        error=row.error,
        owner=row.owner,
        lease_until=row.lease_until,
    )


class SemanticIndexRepository:
    """Flush-only generation and publication operations inside caller transactions."""

    def __init__(self, session: Session):
        self.session = session

    def _row(self, generation_id: str, *, lock: bool = False) -> SemanticIndexGeneration:
        statement = select(SemanticIndexGeneration).where(
            SemanticIndexGeneration.generation_id == generation_id
        )
        if lock:
            statement = statement.with_for_update()
        row = self.session.scalar(statement.execution_options(populate_existing=True))
        if row is None:
            raise LookupError("Semantic generation not found")
        return row

    def get_generation(self, generation_id: str) -> IndexGeneration | None:
        """Return a generation record or None when its ID is not present."""
        row = self.session.get(SemanticIndexGeneration, generation_id)
        return None if row is None else _generation(row)

    def list_generations(self, scope: IndexScope | None = None) -> list[IndexGeneration]:
        """List generations in creation order, optionally within one scope."""
        statement = select(SemanticIndexGeneration).order_by(
            SemanticIndexGeneration.created_at.desc(), SemanticIndexGeneration.generation_id
        )
        if scope is not None:
            statement = statement.where(SemanticIndexGeneration.scope_key == _scope_key(scope))
        return [_generation(row) for row in self.session.scalars(statement)]

    def get_publication(self, scope: IndexScope) -> SemanticIndexPublication | None:
        """Return the publication pointer for the exact candidate scope."""
        row = self.session.get(SemanticIndexPublication, _scope_key(scope))
        if row is not None and row.scope_json != scope.model_dump():
            raise ValueError("Publication scope identity conflicts with ontology version")
        return row

    def _lock_scope(self, scope: IndexScope) -> SemanticIndexPublication:
        """Lock and return the publication pointer used for compare-and-swap writes."""
        values = dict(
            scope_key=_scope_key(scope),
            scope_json=scope.model_dump(),
            **scope.model_dump(),
            policy_json={},
        )
        dialect = self.session.get_bind().dialect.name
        if dialect == "mysql":
            mysql_statement = mysql_insert(SemanticIndexPublication).values(**values)
            self.session.execute(
                mysql_statement.on_duplicate_key_update(
                    scope_key=mysql_statement.inserted.scope_key
                )
            )
        elif dialect == "sqlite":
            sqlite_statement = (
                sqlite_insert(SemanticIndexPublication)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["scope_key"])
            )
            self.session.execute(sqlite_statement)
        else:
            raise RuntimeError(
                "Semantic publication requires MySQL (SQLite is supported for local tests)"
            )
        row = self.session.scalar(
            select(SemanticIndexPublication)
            .where(SemanticIndexPublication.scope_key == _scope_key(scope))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise RuntimeError("Semantic publication scope was not created")
        if row.scope_json != scope.model_dump():
            raise ValueError("Publication scope identity conflicts with ontology version")
        return row

    def create_generation(
        self,
        scope: IndexScope,
        *,
        generation_id: str | None = None,
        graph_revision: int | None = None,
        owner: str | None = None,
        lease_until: datetime | None = None,
    ) -> IndexGeneration:
        """Create one immutable generation identity and its initial build state."""
        if (scope.kind == "entity") != (graph_revision is not None) or (
            graph_revision is not None and graph_revision < 0
        ):
            raise ValueError(
                "Entity generation requires a graph revision; concept revision must be absent"
            )
        identifier = uuid4().hex if generation_id is None else generation_id
        if not identifier or len(identifier) > 128:
            raise ValueError("Invalid generation ID")
        existing = self.get_generation(identifier)
        if existing is not None:
            if existing.scope != scope or existing.graph_revision != graph_revision:
                raise ValueError(
                    "A generation ID is immutable and cannot represent a different scope or revision"
                )
            return existing
        self._lock_scope(scope)
        row = SemanticIndexGeneration(
            generation_id=identifier,
            scope_key=_scope_key(scope),
            scope_json=scope.model_dump(),
            graph_revision=graph_revision,
            owner=owner,
            lease_until=lease_until,
        )
        self.session.add(row)
        self.session.flush()
        return _generation(row)

    def claim_build(
        self,
        scope: IndexScope,
        *,
        graph_revision: int | None,
        owner: str,
        now: datetime,
        lease_seconds: float,
    ) -> IndexGeneration:
        """Acquire the scope build lease or reject a conflicting live owner."""
        self._lock_scope(scope)
        rows = list(
            self.session.scalars(
                select(SemanticIndexGeneration)
                .where(SemanticIndexGeneration.scope_key == _scope_key(scope))
                .order_by(SemanticIndexGeneration.created_at.desc())
                .with_for_update()
            )
        )
        for row in rows:
            if row.graph_revision == graph_revision and row.status in {"active", "ready"}:
                return _generation(row)
        for row in rows:
            if row.status == "building" and row.lease_until is not None and row.lease_until > now:
                raise BuildLeaseConflict("A live build lease already owns this publication scope")
        for row in rows:
            if row.status == "building" and row.graph_revision != graph_revision:
                row.status, row.error, row.finished_at = (
                    "superseded",
                    "lease expired after graph revision changed",
                    now,
                )
                row.owner, row.lease_until = None, None
        reusable = next(
            (
                row
                for row in rows
                if row.graph_revision == graph_revision and row.status in {"building", "failed"}
            ),
            None,
        )
        if reusable is None:
            return self.create_generation(
                scope,
                graph_revision=graph_revision,
                owner=owner,
                lease_until=now + timedelta(seconds=lease_seconds),
            )
        reusable.status, reusable.owner, reusable.error = "building", owner, None
        reusable.lease_until, reusable.finished_at = now + timedelta(seconds=lease_seconds), None
        self.session.flush()
        return _generation(reusable)

    def _check_owner(self, row, *, owner: str | None, now: datetime) -> None:
        if owner is not None and (
            row.status != "building"
            or row.owner != owner
            or row.lease_until is None
            or row.lease_until <= now
        ):
            raise BuildLeaseConflict("Build lease expired or belongs to another owner")

    def renew_lease(
        self, generation_id: str, *, owner: str, now: datetime, lease_seconds: float
    ) -> IndexGeneration:
        """Extend a build lease only while the caller still owns it."""
        row = self._row(generation_id, lock=True)
        self._check_owner(row, owner=owner, now=now)
        row.lease_until = now + timedelta(seconds=lease_seconds)
        self.session.flush()
        return _generation(row)

    def update_progress(
        self,
        generation_id: str,
        *,
        expected_count: int,
        written_count: int,
        checksum: str,
        embedded: int,
        reused: int,
        owner: str,
        now: datetime,
    ) -> IndexGeneration:
        """Persist counters and checksum for the active leased build."""
        row = self._row(generation_id, lock=True)
        self._check_owner(row, owner=owner, now=now)
        row.expected_count, row.written_count, row.checksum = (
            expected_count,
            written_count,
            checksum,
        )
        row.embedded, row.reused = embedded, reused
        self.session.flush()
        return _generation(row)

    def mark_ready(
        self,
        generation_id: str,
        *,
        expected_count: int,
        written_count: int,
        checksum: str,
        owner: str | None = None,
        now: datetime | None = None,
    ) -> IndexGeneration:
        """Mark a fully written generation ready after validating its receipt."""
        row = self._row(generation_id, lock=True)
        now = _utc_now() if now is None else now
        if row.status in {"ready", "active", "retired"}:
            if (row.expected_count, row.written_count, row.checksum) != (
                expected_count,
                written_count,
                checksum,
            ):
                raise ValueError("Verified generation data is immutable")
            return _generation(row)
        self._check_owner(row, owner=owner, now=now)
        if (
            row.status != "building"
            or expected_count != written_count
            or expected_count < 0
            or len(checksum) != 64
        ):
            raise ValueError("Only a completely verified building generation can become ready")
        row.expected_count, row.written_count, row.checksum = (
            expected_count,
            written_count,
            checksum,
        )
        row.status, row.error, row.finished_at = "ready", None, now
        row.owner, row.lease_until = None, None
        self.session.flush()
        return _generation(row)

    def update_outcome(
        self,
        generation_id: str,
        *,
        status: Literal["failed", "superseded"],
        error: str,
        owner: str | None = None,
    ) -> IndexGeneration:
        """Finish a failed or superseded build and retain its diagnostic."""
        row = self._row(generation_id, lock=True)
        if row.status in {"active", "retired"}:
            raise ValueError(
                "An active or retired generation cannot be overwritten by build failure"
            )
        if owner is not None and row.owner != owner:
            raise BuildLeaseConflict("Build lease belongs to another owner")
        row.status, row.error, row.finished_at = status, error, _utc_now()
        row.owner, row.lease_until = None, None
        self.session.flush()
        return _generation(row)

    def publication_status(self, scope: IndexScope) -> IndexPublicationStatus:
        """Read the active generation and policy associated with a scope."""
        row = self.get_publication(scope)
        if row is None or row.active_generation_id is None:
            return IndexPublicationStatus(scope=scope)
        generation = self._row(row.active_generation_id)
        if generation.scope_json != scope.model_dump() or generation.status != "active":
            raise RuntimeError("Semantic publication references an invalid generation")
        return IndexPublicationStatus(
            scope=scope,
            generation_id=row.active_generation_id,
            graph_revision=row.graph_revision,
            status="ready",
            calibration_id=row.calibration_id,
            policy=dict(row.policy_json),
        )

    def publish(
        self,
        generation_id: str,
        *,
        expected_active_generation: str | None,
        calibration_id: str | None = None,
        policy: dict[str, Any] | None = None,
    ) -> IndexPublicationStatus:
        """Atomically advance the active pointer if the expected value is current."""
        # Read immutable scope first; every publisher then locks scope before generation.
        candidate = self._row(generation_id)
        scope = IndexScope.model_validate(candidate.scope_json)
        pointer = self._lock_scope(scope)
        candidate = self._row(generation_id, lock=True)
        if pointer.active_generation_id == generation_id and candidate.status == "active":
            return self.publication_status(scope)
        if pointer.active_generation_id != expected_active_generation:
            raise PublicationConflict("Publication pointer changed while building")
        if candidate.status != "ready":
            raise ValueError("Only a ready generation can be published")
        if pointer.graph_revision is not None and (
            candidate.graph_revision is None or candidate.graph_revision < pointer.graph_revision
        ):
            raise PublicationConflict("An older graph revision cannot replace the publication")
        selected_policy = {} if policy is None else dict(policy)
        _validate_policy(calibration_id, selected_policy)
        if pointer.active_generation_id is not None:
            previous = self._row(pointer.active_generation_id, lock=True)
            previous.status = "retired"
        candidate.status = "active"
        pointer.active_generation_id, pointer.graph_revision = (
            generation_id,
            candidate.graph_revision,
        )
        pointer.calibration_id, pointer.policy_json = calibration_id, selected_policy
        self.session.flush()
        return self.publication_status(scope)

    def attach_calibration(
        self,
        scope: IndexScope,
        generation_id: str,
        *,
        expected_active_generation: str,
        graph_revision: int | None,
        calibration_id: str,
        policy: dict[str, Any],
    ) -> IndexPublicationStatus:
        """Attach a verified report hash without changing immutable candidate rows.

        calibration_id is the SHA-256 of the immutable approved report file;
        the evaluator's original calibration identity remains inside that file.
        """
        _validate_policy(calibration_id, policy)
        if re.fullmatch(r"[0-9a-f]{64}", calibration_id) is None:
            raise ValueError("Attached calibration must identify an immutable report hash")
        pointer = self._lock_scope(scope)
        candidate = self._row(generation_id, lock=True)
        if (
            pointer.active_generation_id != expected_active_generation
            or pointer.active_generation_id != generation_id
            or candidate.status != "active"
            or candidate.scope_json != scope.model_dump()
            or pointer.graph_revision != graph_revision
            or candidate.graph_revision != graph_revision
        ):
            raise PublicationConflict(
                "Calibration scope, active publication or graph revision changed"
            )
        if pointer.calibration_id == calibration_id:
            if pointer.policy_json != policy:
                raise ValueError("Calibration report provenance is immutable")
            return self.publication_status(scope)
        pointer.calibration_id, pointer.policy_json = calibration_id, dict(policy)
        self.session.flush()
        return self.publication_status(scope)

    def retire(self, generation_id: str) -> IndexGeneration:
        """Retire a non-active generation after its lease and status checks pass."""
        candidate = self._row(generation_id)
        pointer = self._lock_scope(IndexScope.model_validate(candidate.scope_json))
        candidate = self._row(generation_id, lock=True)
        if pointer.active_generation_id == generation_id or candidate.status == "active":
            raise ValueError("The active generation is protected from retirement and deletion")
        if (
            candidate.status == "building"
            and candidate.lease_until is not None
            and candidate.lease_until > _utc_now()
        ):
            raise BuildLeaseConflict("A live build lease protects this generation")
        candidate.status, candidate.owner, candidate.lease_until = "retired", None, None
        self.session.flush()
        return _generation(candidate)
