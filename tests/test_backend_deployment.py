"""Render the real Compose model and execute boot scripts without external I/O."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def platform_environment():
    return {
        key: os.environ[key]
        for key in ("PATH", "SystemRoot", "COMSPEC", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }


@pytest.fixture
def compose_model(tmp_path):
    compose = shutil.which("docker-compose")
    docker = shutil.which("docker")
    if compose is not None:
        command = [compose]
    elif docker is not None:
        command = [docker, "compose"]
    else:
        pytest.skip("Docker Compose is required to render the deployment model")
        return
    env_file = tmp_path / "compose.env"
    env_file.write_text(
        "MYSQL_ROOT_PASSWORD=test-root-password\n"
        "MYSQL_DATABASE=gustobot\n"
        "MYSQL_USER=gustobot\n"
        "MYSQL_PASSWORD=test-application-password\n"
        "DATABASE_URL=mysql+pymysql://gustobot:test-application-password@mysql:3306/gustobot?charset=utf8mb4\n"
        "NEO4J_PASSWORD=test-graph-password\n"
        "LLM_API_KEY=\nEMBEDDING_API_KEY=\n",
        encoding="utf-8",
    )
    process = subprocess.run(
        command
        + [
            "--profile",
            "*",
            "--env-file",
            str(env_file),
            "-f",
            str(ROOT / "docker-compose.yml"),
            "config",
            "--format",
            "json",
        ],
        env=platform_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def test_default_compose_runs_only_application_and_three_authoritative_stores(compose_model):
    services = compose_model["services"]
    active = {name for name, service in services.items() if not service.get("profiles")}
    assert active == {"backend", "mysql", "neo4j", "milvus"}
    assert set(services["backend"]["depends_on"]) == {"mysql", "neo4j", "milvus"}
    assert services["redis"]["profiles"] == ["cache"]
    assert services["backend"]["environment"]["DATABASE_URL"].startswith("mysql+pymysql://")
    assert services["backend"]["environment"]["KNOWLEDGE_DOMAIN_FILE"].endswith(".yaml")


def test_milvus_uses_persistent_embedded_etcd_and_read_only_configuration(compose_model):
    milvus = compose_model["services"]["milvus"]
    assert milvus["environment"]["ETCD_USE_EMBED"] == "true"
    assert milvus["environment"]["ETCD_DATA_DIR"] == "/var/lib/milvus/etcd"
    assert milvus["environment"]["COMMON_STORAGETYPE"] == "local"
    mounts = {volume["target"]: volume for volume in milvus["volumes"]}
    assert mounts["/var/lib/milvus"]["type"] == "volume"
    assert mounts["/milvus/configs/embedEtcd.yaml"]["read_only"] is True
    assert mounts["/milvus/configs/user.yaml"]["read_only"] is True


def test_backend_import_needs_no_retired_vendor_or_optional_redis(tmp_path):
    program = textwrap.dedent(
        """
        import builtins
        import socket
        import sys

        original_import = builtins.__import__
        blocked = (
            'lightrag', 'gustobot.application.services.lightrag_service',
            'gustobot.application.agents.text2sql', 'kb_ingest', 'kb_service',
            'pgvector', 'psycopg2', 'redis',
        )

        def guarded_import(name, *args, **kwargs):
            if any(name == item or name.startswith(item + '.') for item in blocked):
                raise AssertionError('Retired or optional backend imported: ' + name)
            return original_import(name, *args, **kwargs)

        def deny_connection(*args, **kwargs):
            raise AssertionError('Backend import attempted an external connection')

        builtins.__import__ = guarded_import
        socket.socket.connect = deny_connection
        sys.path.insert(0, sys.argv[1])
        import gustobot.main
        assert gustobot.main.application is not None
        """
    )
    environment = platform_environment()
    environment.update(
        DATABASE_URL="mysql+pymysql://offline:offline@unused.invalid/gustobot",
        KNOWLEDGE_DOMAIN_FILE=str(ROOT / "gustobot/config/domains/recipes.yaml"),
        LLM_API_KEY="",
        EMBEDDING_API_KEY="",
    )
    process = subprocess.run(
        [sys.executable, "-c", program, str(ROOT)],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == 0, process.stdout + process.stderr


def bash_executable():
    if os.name == "nt":
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        if candidate.is_file():
            return str(candidate)
        pytest.skip("Git Bash is required to execute POSIX container entrypoints on Windows")
    command = shutil.which("bash")
    if command is None:
        pytest.skip("Bash is required to execute container entrypoints")
    return command


def shell_path(path):
    value = path.resolve().as_posix()
    if os.name == "nt":
        return f"/{value[0].lower()}{value[2:]}"
    return value


@pytest.mark.parametrize("script", ["backend_entrypoint.sh", "docker_entrypoint.sh"])
@pytest.mark.parametrize("migration_exit", [0, 17])
def test_boot_checks_schema_before_start_and_stops_on_schema_failure(
    tmp_path, script, migration_exit
):
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    log = tmp_path / "boot.log"
    python = binary_dir / "python"
    python.write_text(
        '#!/bin/sh\nprintf "python %s\\n" "$*" >> "$BOOT_LOG"\n' 'exit "$MIGRATION_EXIT"\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    application = tmp_path / "application.sh"
    application.write_text('#!/bin/sh\nprintf "application\\n" >> "$BOOT_LOG"\n', encoding="utf-8")
    application.chmod(0o755)
    environment = platform_environment()
    environment.update(
        PATH=f"{shell_path(binary_dir)}:/usr/bin:/bin",
        BOOT_LOG=shell_path(log),
        MIGRATION_EXIT=str(migration_exit),
    )
    process = subprocess.run(
        [
            bash_executable(),
            "--noprofile",
            "--norc",
            shell_path(ROOT / "scripts" / script),
            "/bin/sh",
            shell_path(application),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == migration_exit, process.stderr
    expected = ["python scripts/migrate_database.py --check"]
    if migration_exit == 0:
        expected.append("application")
    assert log.read_text(encoding="utf-8").splitlines() == expected


def test_candidate_worker_is_opt_in_and_uses_identical_scope_configuration():
    from pathlib import Path

    import yaml

    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    backend = compose["services"]["backend"]
    worker = compose["services"]["semantic-indexer"]
    assert worker["profiles"] == ["semantic"]
    assert "ports" not in worker
    assert worker["environment"] == backend["environment"]
    assert worker["command"][:4] == ["python", "-m", "scripts.build_semantic_index", "watch"]
    assert "SEMANTIC_EMBEDDING_REVISION" in worker["environment"]
    assert "SEMANTIC_LINKING_MODE" in backend["environment"]
    assert "--batch-size" in worker["command"]
    assert "SEMANTIC_INDEX_BATCH_SIZE" in worker["environment"]


def test_schema_migration_requires_the_explicit_setup_profile():
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    setup = compose["services"]["migrate"]
    assert setup["profiles"] == ["setup"]
    assert setup["entrypoint"] == []
    assert setup["command"] == ["python", "scripts/migrate_database.py"]
    assert set(setup["depends_on"]) == {"mysql"}


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory):
    source = tmp_path_factory.mktemp("wheel-source")
    for directory in ("gustobot", "scripts", "migrations", "eval"):
        shutil.copytree(
            ROOT / directory,
            source / directory,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    for filename in ("pyproject.toml", "requirements.txt", "README.md", "LICENSE"):
        shutil.copyfile(ROOT / filename, source / filename)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from setuptools.build_meta import build_wheel; build_wheel('wheels')",
        ],
        cwd=source,
        env=platform_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (wheel,) = (source / "wheels").glob("*.whl")
    return wheel


def test_wheel_packages_operational_clis(built_wheel):
    with zipfile.ZipFile(built_wheel) as wheel:
        paths = set(wheel.namelist())
    assert {
        "scripts/build_semantic_index.py",
        "scripts/evaluate_knowledge.py",
        "scripts/import_knowledge.py",
        "scripts/migrate_database.py",
        "scripts/verify_knowledge_snapshot.py",
        "migrations/__init__.py",
    } <= paths


def test_wheel_bundles_frozen_evaluation_and_the_scoped_overlay_factory(built_wheel):
    with zipfile.ZipFile(built_wheel) as wheel:
        paths = set(wheel.namelist())
        assert "eval/knowledge/runtime_factory.py" in paths
        assert json.loads(wheel.read("eval/knowledge/questions.jsonl").splitlines()[0])
        assert json.loads(wheel.read("eval/knowledge/calibration.jsonl").splitlines()[0])
        assert "gustobot/config/domains/recipes.yaml" in paths
        assert "gustobot/config/ontologies/recipes.ttl" in paths
        assert "gustobot/config/ontologies/recipes.shacl.ttl" in paths
