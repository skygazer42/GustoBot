"""Create or verify a local backup manifest; never connect, dump, delete or restore stores."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# These domain modules have no application settings or dotenv imports.
from gustobot.domain.formal_ontology import load_formal_ontology
from gustobot.domain.linking import (
    INDEX_SCHEMA_VERSION,
    IndexGeneration,
    IndexPublicationStatus,
)

_Model = TypeVar("_Model", bound=BaseModel)
_DIGEST = r"^[0-9a-f]{64}$"


class SnapshotError(ValueError):
    """A stable error code without file contents, credentials or raw manifests."""


class _Record(BaseModel):
    """Base contract that forbids unknown fields in snapshot records."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ModelScope(_Record):
    """Domain and ontology identity that stored artifacts must match."""

    domain_id: str = Field(min_length=1)
    ontology_version: str = Field(min_length=1)
    ontology_fingerprint: str = Field(pattern=_DIGEST)


class ExpectedScope(ModelScope):
    """Optional expected vector-index identity used to compare a snapshot."""

    embedding_fingerprint: str | None = Field(default=None, pattern=_DIGEST)
    index_schema_version: str = INDEX_SCHEMA_VERSION
    kind: Literal["concept", "entity"] | None = None


class ModelFiles(_Record):
    """Ontology, shape graph, and local resource files included in a snapshot."""

    ontology: str
    shapes: str
    resources: list[str] = Field(default_factory=list)


class StoreFiles(_Record):
    """Store dump and metadata paths supplied by the backup operator."""

    dump: str
    metadata: str


class SourceFile(_Record):
    """Source version and optional uploaded asset files to include in a backup."""

    source_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    asset_id: str | None = None
    path: str


class AssetFile(_Record):
    """Uploaded asset identity and its path relative to the snapshot root."""

    asset_id: str = Field(min_length=1)
    path: str


class VectorBackups(_Record):
    """Optional exported document and semantic candidate vector backups."""

    documents: str | None = None
    candidates: str | None = None


class SnapshotSpec(_Record):
    """Operator-supplied inventory of model, store, source, and vector files."""

    snapshot_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    model: ModelFiles
    mysql: StoreFiles
    neo4j: StoreFiles
    sources: list[SourceFile]
    assets: list[AssetFile] = Field(default_factory=list)
    documents: str
    candidates: str
    vector_backups: VectorBackups = Field(default_factory=VectorBackups)


class SourcePublication(_Record):
    """Published source version and optional asset identity recorded by a store."""

    source_id: str
    version: str
    ontology_version: str
    status: Literal["ready", "graph_ready"]
    asset_id: str | None = None


class StoreMetadata(_Record):
    """Captured store scope, graph revision, and initialization state."""

    capture_id: str
    scope: ModelScope
    graph_revision: int | None = Field(ge=0)
    graph_state: Literal["ready", "uninitialized", "initializing"] = "ready"


class MySQLMetadata(StoreMetadata):
    """MySQL schema revisions, published sources, and managed asset IDs."""

    schema_revisions: list[str]
    sources: list[SourcePublication]
    asset_ids: list[str]


class GraphMetadata(StoreMetadata):
    """Neo4j source and sample identities plus numeric projection version."""

    source_ids: list[str]
    sample_entity_ids: list[str]
    numeric_projection_version: str | None = None


class DocumentPublication(_Record):
    """Document source version and entity links exposed by vector metadata."""

    source_id: str
    version: str
    entity_ids: list[str] = Field(default_factory=list)


class DocumentMetadata(_Record):
    """Document vector collection configuration and published source versions."""

    capture_id: str
    scope: ModelScope
    collection: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    dimension: int = Field(gt=0)
    publications: list[DocumentPublication]


class CandidateMetadata(_Record):
    """Candidate publication pointers and generation records from the vector store."""

    capture_id: str
    publications: list[IndexPublicationStatus]
    generations: list[IndexGeneration]


class Artifact(_Record):
    """Relative artifact path, byte count, and SHA-256 content checksum."""

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=_DIGEST)


class SnapshotManifest(_Record):
    """Generated manifest binding a snapshot spec to captured state and hashes."""

    manifest_schema: Literal["gustobot_knowledge_snapshot_v1"] = "gustobot_knowledge_snapshot_v1"
    created_at: str
    spec: SnapshotSpec
    scope: ModelScope
    graph_revision: int | None
    graph_state: str
    numeric_projection_version: str | None
    artifacts: dict[str, Artifact]


class VerificationReport(_Record):
    """Read-only verification result, rebuild requirements, and restoration checklist."""
    valid: bool
    snapshot_id: str | None = None
    scope: ModelScope | None = None
    graph_revision: int | None = None
    candidate_compatible: bool = False
    document_rebuild_required: bool = True
    numeric_projection_rebuild_required: bool = True
    database_restore_verified: Literal[False] = False
    verification_basis: str = "file_hashes_compiled_model_and_exported_metadata"
    errors: list[str] = Field(default_factory=list)
    rebuild_reasons: list[str] = Field(default_factory=list)
    restore_checklist: list[str] = Field(default_factory=list)


def _unique_pairs(items):
    result = {}
    for item in items:
        key = item.source_id, item.version
        if key in result:
            raise SnapshotError("duplicate_source_version")
        result[key] = item
    return result


def _json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise SnapshotError("duplicate_json_key")
        value[key] = item
    return value


def _read_record(path: Path, record: type[_Model]) -> _Model:
    if path.name == ".env" or path.name.startswith(".env."):
        raise SnapshotError("env_artifact_forbidden")
    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_json_object)
    return record.model_validate_json(json.dumps(payload, allow_nan=False))


def _path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    windows = PureWindowsPath(relative)
    if candidate.is_absolute() or windows.drive or windows.root:
        raise SnapshotError("artifact_outside_bundle")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise SnapshotError("artifact_outside_bundle")
    if resolved.name == ".env" or resolved.name.startswith(".env."):
        raise SnapshotError("env_artifact_forbidden")
    if not resolved.is_file():
        raise SnapshotError("missing_artifact")
    return resolved


def _artifact_paths(spec: SnapshotSpec) -> dict[str, str]:
    """Map every declared backup artifact to its stable manifest key and path."""
    result = {
        "model.ontology": spec.model.ontology,
        "model.shapes": spec.model.shapes,
        "mysql.dump": spec.mysql.dump,
        "mysql.metadata": spec.mysql.metadata,
        "neo4j.dump": spec.neo4j.dump,
        "neo4j.metadata": spec.neo4j.metadata,
        "documents.metadata": spec.documents,
        "candidates.metadata": spec.candidates,
    }
    for index, path in enumerate(spec.model.resources):
        result[f"model.resource.{index}"] = path
    for index, source in enumerate(spec.sources):
        result[f"source.{index}"] = source.path
    for index, asset in enumerate(spec.assets):
        result[f"asset.{index}"] = asset.path
    for kind in ("documents", "candidates"):
        path = getattr(spec.vector_backups, kind)
        if path is not None:
            result[f"{kind}.vectors"] = path
    return result


def _hash_artifact(root: Path, relative: str) -> Artifact:
    path = _path(root, relative)
    before = path.stat()
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise SnapshotError("artifact_changed_during_hash")
    return Artifact(path=relative, size=after.st_size, sha256=checksum.hexdigest())


def _candidate_reasons(
    metadata: CandidateMetadata,
    scope: ModelScope,
    graph: GraphMetadata,
    expected: ExpectedScope | None,
    has_backup: bool,
) -> list[str]:
    """Explain whether candidate vectors can be reused or must be rebuilt."""
    reasons = []
    if not has_backup:
        reasons.append("candidate_backup_missing")
    if graph.graph_state != "ready":
        reasons.append("graph_scope_uninitialized")
    generations = {item.generation_id: item for item in metadata.generations}
    if len(generations) != len(metadata.generations):
        reasons.append("candidate_generation_ambiguous")
    if len({item.scope.embedding_fingerprint for item in metadata.publications}) > 1:
        reasons.append("candidate_embedding_mismatch")
    for kind in ("concept", "entity"):
        publications = [item for item in metadata.publications if item.scope.kind == kind]
        if len(publications) != 1:
            reasons.append("candidate_scope_missing_or_ambiguous")
            continue
        publication = publications[0]
        candidate_scope = publication.scope
        if (
            ModelScope.model_validate(
                candidate_scope.model_dump(include=set(ModelScope.model_fields))
            )
            != scope
        ):
            reasons.append("candidate_model_scope_mismatch")
        if candidate_scope.index_schema_version != (
            INDEX_SCHEMA_VERSION if expected is None else expected.index_schema_version
        ):
            reasons.append("candidate_schema_mismatch")
        if (
            expected is not None
            and expected.embedding_fingerprint is not None
            and candidate_scope.embedding_fingerprint != expected.embedding_fingerprint
        ):
            reasons.append("candidate_embedding_mismatch")
        revision = graph.graph_revision if kind == "entity" else None
        if publication.status != "ready" or publication.graph_revision != revision:
            reasons.append("candidate_revision_or_publication_mismatch")
        generation = (
            None
            if publication.generation_id is None
            else generations.get(publication.generation_id)
        )
        if generation is None:
            reasons.append("candidate_generation_missing")
        elif (
            generation.scope != candidate_scope
            or generation.graph_revision != revision
            or generation.status != "active"
            or generation.expected_count < 0
            or generation.expected_count != generation.written_count
            or re.fullmatch(_DIGEST, generation.checksum) is None
        ):
            reasons.append("candidate_generation_unverified")
    return sorted(set(reasons))


def _restore_checklist(candidate_compatible: bool) -> list[str]:
    return [
        "Set SEMANTIC_LINKING_MODE=off; stop writers and semantic-indexer, then drain in-flight work.",
        "Restore the matching model bundle, MySQL dump, Neo4j dump and approved source/assets into isolated stores.",
        "Run scripts/migrate_database.py --check and compare restored scope, graph revision, source versions, counts and sample IDs.",
        "Restore compatible document vectors or rebuild approved source publications before enabling document retrieval.",
        (
            "Verify restored candidate generation counts/checksums and scope before reusing the saved pointer."
            if candidate_compatible
            else "Keep semantic linking off; audit/bootstrap scope, publish required numeric projections and rebuild concept/entity candidates."
        ),
        "Complete actual retrieval, QA and failure/restore checks; enable shadow, then on only with matching calibration and approval.",
    ]


def _inspect(
    root: Path, spec: SnapshotSpec, expected: ExpectedScope | None = None
) -> tuple[VerificationReport, str, str | None]:
    """Cross-check captured store metadata and model scope without contacting stores."""
    ontology, shapes = _path(root, spec.model.ontology), _path(root, spec.model.shapes)
    # The executable loader permits this single local imported vocabulary.
    imported = ontology.parent / "schema-recipe-subset.ttl"
    resources = {_path(root, item) for item in spec.model.resources}
    if imported.is_file():
        imported = _path(root, str(imported.relative_to(root)))
        if imported not in resources:
            raise SnapshotError("model_import_not_in_manifest")
    try:
        model = load_formal_ontology(ontology, shapes)
    except SyntaxError as error:
        raise SnapshotError("invalid_model_syntax") from error
    scope = ModelScope(
        domain_id=model.id, ontology_version=model.version, ontology_fingerprint=model.fingerprint
    )
    mysql = _read_record(_path(root, spec.mysql.metadata), MySQLMetadata)
    graph = _read_record(_path(root, spec.neo4j.metadata), GraphMetadata)
    documents = _read_record(_path(root, spec.documents), DocumentMetadata)
    candidates = _read_record(_path(root, spec.candidates), CandidateMetadata)
    for record in (mysql, graph, documents, candidates):
        if record.capture_id != spec.snapshot_id:
            raise SnapshotError("capture_id_mismatch")
    for actual in (mysql.scope, graph.scope, documents.scope):
        if actual != scope:
            raise SnapshotError("model_scope_mismatch")
    if (
        expected is not None
        and ModelScope.model_validate(expected.model_dump(include=set(ModelScope.model_fields)))
        != scope
    ):
        raise SnapshotError("expected_model_scope_mismatch")
    if (mysql.graph_revision, mysql.graph_state) != (graph.graph_revision, graph.graph_state):
        raise SnapshotError("graph_revision_mismatch")
    if graph.graph_state == "initializing" or (graph.graph_state == "ready") != (
        graph.graph_revision is not None
    ):
        raise SnapshotError("graph_scope_not_quiescent")
    approved, published = _unique_pairs(spec.sources), _unique_pairs(mysql.sources)
    asset_ids = {source.asset_id for source in spec.sources if source.asset_id is not None} | {
        asset.asset_id for asset in spec.assets
    }
    if set(mysql.asset_ids) - asset_ids:
        raise SnapshotError("missing_asset_backup")
    for key, source in published.items():
        if key not in approved or source.ontology_version != scope.ontology_version:
            raise SnapshotError("source_publication_mismatch")
        if source.asset_id is not None and (
            source.asset_id not in mysql.asset_ids or source.asset_id not in asset_ids
        ):
            raise SnapshotError("missing_asset_backup")
    if set(graph.source_ids) - {item.source_id for item in spec.sources}:
        raise SnapshotError("graph_source_missing")
    for publication in documents.publications:
        source = published.get((publication.source_id, publication.version))
        if source is None or source.status != "ready":
            raise SnapshotError("document_publication_mismatch")
    reasons = _candidate_reasons(
        candidates, scope, graph, expected, spec.vector_backups.candidates is not None
    )
    if "0003_semantic_index_publication" not in mysql.schema_revisions:
        reasons.append("publication_schema_missing")
    projection_version = model.numeric_projection_version if model.numeric_projections else None
    projection_rebuild = graph.numeric_projection_version != projection_version
    if projection_rebuild:
        reasons.append("numeric_projection_rebuild_required")
    compatible = not reasons
    report = VerificationReport(
        valid=True,
        snapshot_id=spec.snapshot_id,
        scope=scope,
        graph_revision=graph.graph_revision,
        candidate_compatible=compatible,
        document_rebuild_required=bool(documents.publications)
        and spec.vector_backups.documents is None,
        numeric_projection_rebuild_required=projection_rebuild,
        rebuild_reasons=reasons,
        restore_checklist=_restore_checklist(compatible),
    )
    return report, graph.graph_state, projection_version


def create_manifest(
    spec_path: Path, output_path: Path, *, root: Path | None = None
) -> VerificationReport:
    """Hash declared files and write a manifest bound to validated store metadata."""
    root = (spec_path.parent if root is None else root).resolve(strict=True)
    spec = _read_record(spec_path, SnapshotSpec)
    paths = _artifact_paths(spec)
    artifacts = {name: _hash_artifact(root, path) for name, path in paths.items()}
    report, graph_state, projection_version = _inspect(root, spec)
    if output_path.parent.resolve(strict=True) != root:
        raise SnapshotError("manifest_must_be_at_bundle_root")
    manifest = SnapshotManifest(
        created_at=datetime.now(timezone.utc).isoformat(),
        spec=spec,
        scope=ModelScope.model_validate(report.scope),
        graph_revision=report.graph_revision,
        graph_state=graph_state,
        numeric_projection_version=projection_version,
        artifacts=artifacts,
    )
    with output_path.open("x", encoding="utf-8") as stream:
        stream.write(manifest.model_dump_json(indent=2) + "\n")
    return report


def verify_manifest(
    manifest_path: Path,
    *,
    root: Path | None = None,
    expected_scope: dict[str, Any] | ExpectedScope | None = None,
) -> VerificationReport:
    """Verify manifest files, compiled model identity, and exported store metadata."""
    try:
        root = (manifest_path.parent if root is None else root).resolve(strict=True)
        manifest = _read_record(manifest_path, SnapshotManifest)
        expected = (
            ExpectedScope.model_validate(expected_scope)
            if isinstance(expected_scope, dict)
            else expected_scope
        )
        paths = _artifact_paths(manifest.spec)
        if set(paths) != set(manifest.artifacts):
            raise SnapshotError("artifact_inventory_mismatch")
        for name, path in paths.items():
            if _hash_artifact(root, path) != manifest.artifacts[name]:
                raise SnapshotError("artifact_hash_mismatch")
        report, graph_state, projection = _inspect(root, manifest.spec, expected)
        if (
            manifest.scope,
            manifest.graph_revision,
            manifest.graph_state,
            manifest.numeric_projection_version,
        ) != (report.scope, report.graph_revision, graph_state, projection):
            raise SnapshotError("manifest_scope_mismatch")
        return report
    except SnapshotError as error:
        return VerificationReport(valid=False, errors=[str(error)])
    except (OSError, ValueError, ValidationError):
        return VerificationReport(valid=False, errors=["invalid_or_unreadable_snapshot"])


def main(argv: list[str] | None = None) -> int:
    """Create or verify a local snapshot manifest without contacting live stores."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Hash existing artifacts and write a new manifest")
    create.add_argument("--spec", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--root", type=Path)
    verify = commands.add_parser("verify", help="Verify artifacts, scopes and restore requirements")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--root", type=Path)
    verify.add_argument("--expect-scope", type=Path)
    verify.add_argument("--require-candidates", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            report = create_manifest(args.spec, args.output, root=args.root)
        else:
            expected = (
                _read_record(args.expect_scope, ExpectedScope)
                if args.expect_scope is not None
                else None
            )
            report = verify_manifest(args.manifest, root=args.root, expected_scope=expected)
    except SnapshotError as error:
        report = VerificationReport(valid=False, errors=[str(error)])
    except (OSError, ValueError, ValidationError):
        report = VerificationReport(valid=False, errors=["invalid_or_unreadable_snapshot"])
    print(report.model_dump_json(indent=2))
    return (
        0
        if report.valid
        and not (
            args.command == "verify" and args.require_candidates and not report.candidate_compatible
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
