"""
Pytest configuration.

Make the project importable in all environments without requiring an editable install.
Some CI/runner setups use `--import-mode=importlib` or otherwise do not add the repo root
to `sys.path` consistently, so we do it explicitly here.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
