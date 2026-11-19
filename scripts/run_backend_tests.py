"""Run repository tests without loading a developer's dotenv configuration."""

import os
import sys
from pathlib import Path
from unittest.mock import patch


def main(argv: list[str] | None = None) -> int:
    import dotenv
    import pytest
    from pydantic_settings import BaseSettings

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    os.environ.setdefault("DATABASE_URL", "mysql+pymysql://test@127.0.0.1:13316/gustobot_test")
    original_init = BaseSettings.__init__

    def isolated_init(self, *args, **kwargs):
        kwargs["_env_file"] = None
        original_init(self, *args, **kwargs)

    with (
        patch.object(dotenv, "load_dotenv", return_value=False),
        patch.object(BaseSettings, "__init__", isolated_init),
    ):
        return int(pytest.main(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
