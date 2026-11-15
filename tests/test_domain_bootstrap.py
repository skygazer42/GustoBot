"""Run startup shells with fake Python so alternate domains never seed recipes."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("script", ["backend_entrypoint.sh", "docker_entrypoint.sh"])
def test_non_recipe_container_startup_skips_legacy_data(script):
    bash = shutil.which("bash")
    if os.name == "nt":
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        bash = str(candidate) if candidate.is_file() else None
    if bash is None:
        pytest.skip("Bash is required to exercise container entrypoints")
    assert bash is not None
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        INIT_KB_MILVUS="true",
        AUTO_BOOTSTRAP_LIGHTRAG="true",
        INIT_LIGHTRAG_ON_STARTUP="true",
    )
    result = subprocess.run(
        [
            bash,
            "-c",
            'python() { if [ "$1" = "-c" ]; then printf "false\\n"; '
            "else cat >/dev/null; fi; }; export -f python; "
            'exec bash "$1" printf "service-started\\n"',
            "domain-bootstrap-test",
            str(root / "scripts" / script),
        ],
        env=environment,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=15,
    )
    assert "skips legacy recipe LightRAG bootstrap" in result.stdout
    assert "service-started" in result.stdout
    assert "Importing KB dataset" not in result.stdout
    if script == "backend_entrypoint.sh":
        assert "skips legacy Milvus bootstrap" in result.stdout


def test_recipe_lightrag_startup_does_not_seed_legacy_milvus():
    bash = shutil.which("bash")
    if os.name == "nt":
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        bash = str(candidate) if candidate.is_file() else None
    if bash is None:
        pytest.skip("Bash is required to exercise container entrypoints")
    assert bash is not None
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(AUTO_BOOTSTRAP_LIGHTRAG="false", INIT_KB_MILVUS="true")
    result = subprocess.run(
        [
            bash,
            "-c",
            'python() { if [ "$1" = "-c" ]; then case "$2" in '
            '*document_backend*) printf "false\\n" ;; *) printf "true\\n" ;; esac; '
            "else cat >/dev/null; fi; }; export -f python; "
            'exec bash "$1" printf "service-started\\n"',
            "recipe-bootstrap-test",
            str(root / "scripts" / "backend_entrypoint.sh"),
        ],
        env=environment,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=15,
    )
    assert "LightRAG bootstrap disabled" in result.stdout
    assert "skips legacy Milvus bootstrap" in result.stdout
    assert "service-started" in result.stdout
