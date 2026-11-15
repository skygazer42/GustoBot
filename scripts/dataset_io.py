"""Read object records shared by the standalone dataset conversion commands."""

import json
import sys
from pathlib import Path
from typing import Any


def read_any(path: str) -> list[dict[str, Any]]:
    """Read a JSON array or JSONL from a file or stdin; reject malformed records."""
    data = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    if not data.strip():
        return []
    decoded: list[Any]
    if data.lstrip().startswith("["):
        decoded = json.loads(data)
    else:
        decoded = [json.loads(line) for line in data.splitlines() if line.strip()]
    if any(not isinstance(record, dict) for record in decoded):
        raise TypeError("Every dataset record must be a JSON object")
    return decoded
