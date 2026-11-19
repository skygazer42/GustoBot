"""The repeatable test entrypoint must not read a developer's dotenv files."""

import os
import subprocess
import sys
from pathlib import Path


def test_safe_runner_ignores_explicit_and_implicit_dotenv(tmp_path):
    root = Path(__file__).resolve().parents[1]
    dotenv = tmp_path / ".env"
    dotenv.write_text("SENTINEL=should-never-load\n", encoding="utf-8")
    case = tmp_path / "test_no_dotenv.py"
    case.write_text(
        "import os\nimport dotenv\nfrom pydantic_settings import BaseSettings\n"
        "def test_isolated():\n"
        "    class Config(BaseSettings):\n        SENTINEL: str = 'default'\n"
        f"    assert Config(_env_file={str(dotenv)!r}).SENTINEL == 'default'\n"
        f"    assert dotenv.load_dotenv({str(dotenv)!r}) is False\n"
        "    assert 'SENTINEL' not in os.environ\n",
        encoding="utf-8",
    )
    runner = root / "scripts/run_backend_tests.py"
    assert runner.is_file(), "A versioned safe test runner is required"
    environment = {
        key: os.environ[key]
        for key in ("PATH", "SystemRoot", "COMSPEC", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    result = subprocess.run(
        [sys.executable, str(runner), str(case), "-q", "-o", "addopts="],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
