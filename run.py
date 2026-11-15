"""
Convenience wrapper to keep legacy commands working.

The actual CLI lives in `scripts/run.py`, but many docs reference `python run.py ...`.
"""

import runpy
from pathlib import Path


if __name__ == "__main__":
    script_path = Path(__file__).resolve().parent / "scripts" / "run.py"
    runpy.run_path(str(script_path), run_name="__main__")
