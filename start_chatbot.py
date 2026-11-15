"""
Convenience wrapper to keep legacy commands working.

The maintained entrypoint is `scripts/start_chatbot.py`.
"""

import runpy
from pathlib import Path


if __name__ == "__main__":
    script_path = Path(__file__).resolve().parent / "scripts" / "start_chatbot.py"
    runpy.run_path(str(script_path), run_name="__main__")
