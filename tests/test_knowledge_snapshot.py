"""Snapshot checks bind existing artifacts to one model and capture boundary."""

import hashlib
import importlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from gustobot.domain.formal_ontology import load_formal_ontology
from gustobot.domain.linking import INDEX_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]


def api():
    name = "scripts.verify_knowledge_snapshot"
    assert importlib.util.find_spec(name) is not None, "Knowledge snapshot verifier is missing"
    return importlib.import_module(name)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def bundle(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        shutil.copy2(ROOT / "gustobot/config/ontologies" / name, model_dir / name)
    model = load_formal_ontology(model_dir / "recipes.ttl", model_dir / "recipes.shacl.ttl")
    scope = {
        "domain_id": model.id,
        "ontology_version": model.version,
        "ontology_fingerprint": model.fingerprint,
    }
    (tmp_path / "mysql.sql").write_bytes(b"controlled MySQL dump fixture")
    (tmp_path / "neo4j.dump").write_bytes(b"controlled Neo4j dump fixture")
    (tmp_path / "documents.export").write_bytes(b"controlled document vector fixture")
    (tmp_path / "candidates.export").write_bytes(b"controlled candidate vector fixture")
    (tmp_path / "source.txt").write_text("佛跳墙用糖适量。", encoding="utf-8")
    source_version = hashlib.sha256((tmp_path / "source.txt").read_bytes()).hexdigest()
    source = {
        "source_id": "source-a",
        "version": source_version,
        "ontology_version": model.version,
        "status": "ready",
        "asset_id": "asset-a",
    }
    write_json(
        tmp_path / "mysql-scope.json",
        {
            "capture_id": "capture-a",
            "scope": scope,
            "graph_revision": 7,
            "schema_revisions": [
                "0001_application_schema",
                "0002_exact_knowledge_identity",
                "0003_semantic_index_publication",
            ],
            "sources": [source],
            "asset_ids": ["asset-a"],
        },
    )
    write_json(
        tmp_path / "graph-scope.json",
        {
            "capture_id": "capture-a",
            "scope": scope,
            "graph_revision": 7,
            "source_ids": ["source-a"],
            "sample_entity_ids": ["recipe-a"],
            "numeric_projection_version": model.numeric_projection_version,
        },
    )
    write_json(
        tmp_path / "documents.json",
        {
            "capture_id": "capture-a",
            "scope": scope,
            "collection": "documents-fixture",
            "embedding_model": "fixture",
            "dimension": 2,
            "publications": [
                {"source_id": "source-a", "version": source_version, "entity_ids": ["recipe-a"]}
            ],
        },
    )
    publications, generations = [], []
    for kind in ("concept", "entity"):
        index_scope = scope | {
            "embedding_fingerprint": "b" * 64,
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "kind": kind,
        }
        generation_id = "generation-" + kind
        revision = 7 if kind == "entity" else None
        publications.append(
            {
                "scope": index_scope,
                "generation_id": generation_id,
                "graph_revision": revision,
                "status": "ready",
                "calibration_id": None,
                "policy": {},
            }
        )
        generations.append(
            {
                "generation_id": generation_id,
                "scope": index_scope,
                "graph_revision": revision,
                "status": "active",
                "expected_count": 1,
                "written_count": 1,
                "checksum": "c" * 64,
            }
        )
    write_json(
        tmp_path / "candidates.json",
        {"capture_id": "capture-a", "publications": publications, "generations": generations},
    )
    spec = {
        "snapshot_id": "capture-a",
        "model": {
            "ontology": "model/recipes.ttl",
            "shapes": "model/recipes.shacl.ttl",
            "resources": ["model/schema-recipe-subset.ttl"],
        },
        "mysql": {"dump": "mysql.sql", "metadata": "mysql-scope.json"},
        "neo4j": {"dump": "neo4j.dump", "metadata": "graph-scope.json"},
        "sources": [
            {
                "source_id": "source-a",
                "version": source_version,
                "asset_id": "asset-a",
                "path": "source.txt",
            }
        ],
        "documents": "documents.json",
        "candidates": "candidates.json",
        "vector_backups": {"documents": "documents.export", "candidates": "candidates.export"},
    }
    write_json(tmp_path / "snapshot-input.json", spec)
    return tmp_path


def create(bundle):
    return api().create_manifest(bundle / "snapshot-input.json", bundle / "manifest.json")


def edit(bundle, name, change):
    path = bundle / name
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    write_json(path, data)


def test_manifest_verifies_all_artifacts_without_claiming_a_database_restore(bundle):
    report = create(bundle)
    assert report.valid and report.candidate_compatible and not report.document_rebuild_required
    assert not report.database_restore_verified
    verified = api().verify_manifest(bundle / "manifest.json")
    assert verified.valid and verified.graph_revision == 7
    assert verified.scope.ontology_version == "2026-11-17.1"
    assert verified.restore_checklist[0].startswith("Set SEMANTIC_LINKING_MODE=off")
    assert json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))["artifacts"]


def test_changed_dump_and_missing_source_are_detected_after_manifest_creation(bundle):
    create(bundle)
    (bundle / "mysql.sql").write_bytes(b"changed")
    report = api().verify_manifest(bundle / "manifest.json")
    assert not report.valid and "artifact_hash_mismatch" in report.errors
    (bundle / "mysql.sql").write_bytes(b"controlled MySQL dump fixture")
    (bundle / "source.txt").unlink()
    report = api().verify_manifest(bundle / "manifest.json")
    assert not report.valid and "missing_artifact" in report.errors


@pytest.mark.parametrize(
    "name,field,value,expected",
    [
        ("graph-scope.json", "graph_revision", 8, "graph_revision_mismatch"),
        ("mysql-scope.json", "capture_id", "other-capture", "capture_id_mismatch"),
    ],
)
def test_mismatched_capture_or_revision_cannot_create_a_coherent_manifest(
    bundle, name, field, value, expected
):
    edit(bundle, name, lambda data: data.update({field: value}))
    with pytest.raises(ValueError, match=expected):
        create(bundle)
    assert not (bundle / "manifest.json").exists()


def test_wrong_model_scope_or_unbacked_publication_asset_is_rejected(bundle):
    edit(bundle, "documents.json", lambda data: data["scope"].update(ontology_fingerprint="d" * 64))
    with pytest.raises(ValueError, match="model_scope_mismatch"):
        create(bundle)
    edit(
        bundle,
        "documents.json",
        lambda data: data["scope"].update(
            ontology_fingerprint=json.loads(
                (bundle / "mysql-scope.json").read_text(encoding="utf-8")
            )["scope"]["ontology_fingerprint"]
        ),
    )
    edit(bundle, "mysql-scope.json", lambda data: data["asset_ids"].append("missing-asset"))
    with pytest.raises(ValueError, match="missing_asset_backup"):
        create(bundle)


def test_no_vector_backup_remains_a_valid_core_snapshot_requiring_off_and_rebuild(bundle):
    edit(bundle, "snapshot-input.json", lambda data: data.update(vector_backups={}))
    report = create(bundle)
    assert report.valid and not report.candidate_compatible and report.document_rebuild_required
    assert "candidate_backup_missing" in report.rebuild_reasons
    assert any("rebuild" in step.lower() for step in report.restore_checklist)


def test_candidate_embedding_and_revision_incompatibility_are_explicit(bundle):
    create(bundle)
    expected = json.loads((bundle / "mysql-scope.json").read_text(encoding="utf-8"))["scope"] | {
        "embedding_fingerprint": "e" * 64
    }
    report = api().verify_manifest(bundle / "manifest.json", expected_scope=expected)
    assert report.valid and not report.candidate_compatible
    assert "candidate_embedding_mismatch" in report.rebuild_reasons


def test_unmatched_document_source_version_cannot_be_declared_published(bundle):
    edit(bundle, "documents.json", lambda data: data["publications"][0].update(version="unknown"))
    with pytest.raises(ValueError, match="document_publication_mismatch"):
        create(bundle)


def test_cli_outputs_only_summary_and_never_raw_input_or_secret_fields(bundle, capsys):
    module = api()
    assert (
        module.main(
            [
                "create",
                "--spec",
                str(bundle / "snapshot-input.json"),
                "--output",
                str(bundle / "manifest.json"),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "controlled MySQL dump fixture" not in output and "佛跳墙" not in output
    assert (
        module.main(["verify", "--manifest", str(bundle / "manifest.json"), "--require-candidates"])
        == 0
    )
    edit(bundle, "manifest.json", lambda data: data.update(password="secret-value-must-not-appear"))
    assert module.main(["verify", "--manifest", str(bundle / "manifest.json")]) != 0
    output = capsys.readouterr().out
    assert "secret-value-must-not-appear" not in output


def test_env_files_and_paths_outside_bundle_are_not_read_and_manifest_is_not_overwritten(bundle):
    edit(
        bundle, "snapshot-input.json", lambda data: data["sources"][0].update(path="../outside.txt")
    )
    with pytest.raises(ValueError, match="artifact_outside_bundle"):
        create(bundle)
    (bundle / ".env").write_text("DO_NOT_READ=private", encoding="utf-8")
    edit(bundle, "snapshot-input.json", lambda data: data["sources"][0].update(path=".env"))
    with pytest.raises(ValueError, match="env_artifact_forbidden"):
        create(bundle)


def test_manifest_creation_refuses_to_overwrite_existing_capture(bundle):
    create(bundle)
    original = (bundle / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        create(bundle)
    assert (bundle / "manifest.json").read_bytes() == original


def test_stale_candidate_generation_forces_rebuild_but_preserves_core_backup(bundle):
    edit(bundle, "candidates.json", lambda data: data["publications"][1].update(graph_revision=6))
    report = create(bundle)
    assert report.valid and not report.candidate_compatible
    assert "candidate_revision_or_publication_mismatch" in report.rebuild_reasons


def test_pre_publication_schema_can_be_preserved_but_cannot_reuse_candidate_pointer(bundle):
    edit(
        bundle,
        "mysql-scope.json",
        lambda data: data.update(
            schema_revisions=["0001_application_schema", "0002_exact_knowledge_identity"]
        ),
    )
    edit(bundle, "candidates.json", lambda data: data.update(publications=[], generations=[]))
    report = create(bundle)
    assert report.valid and not report.candidate_compatible
    assert "publication_schema_missing" in report.rebuild_reasons


def test_invalid_model_syntax_is_reported_without_echoing_sensitive_content(bundle, capsys):
    create(bundle)
    path = bundle / "model/recipes.ttl"
    path.write_text('"private-model-value-must-not-appear" broken turtle', encoding="utf-8")
    module = api()
    assert (
        module.main(
            [
                "create",
                "--spec",
                str(bundle / "snapshot-input.json"),
                "--output",
                str(bundle / "new-manifest.json"),
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "private-model-value-must-not-appear" not in captured.out + captured.err


def test_snapshot_cli_imports_no_runtime_settings_or_dotenv(bundle):
    import subprocess
    import sys

    code = """
import runpy
import sys
from pathlib import Path

def forbidden(event, arguments):
    if event == 'open' and isinstance(arguments[0], (str, bytes)):
        name = Path(arguments[0]).name
        if name == '.env' or name.startswith('.env.'):
            raise RuntimeError('dotenv access is forbidden')

sys.addaudithook(forbidden)
script, spec, output = sys.argv[1:]
namespace = runpy.run_path(script, run_name='snapshot_import')
assert 'gustobot.config.settings' not in sys.modules
raise SystemExit(namespace['main'](['create', '--spec', spec, '--output', output]))
"""
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(ROOT / "scripts/verify_knowledge_snapshot.py"),
            str(bundle / "snapshot-input.json"),
            str(bundle / "manifest.json"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["valid"]
