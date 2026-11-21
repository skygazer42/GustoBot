#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dataset_io import read_any


def qa_to_alpaca(obj: dict[str, Any]) -> dict[str, str]:
    """Convert one source/target pair into an Alpaca instruction record."""
    question = obj["src"]
    answer = obj["tgt"]
    if not isinstance(question, str) or not isinstance(answer, str):
        raise TypeError("src and tgt must be strings")
    return {"instruction": question, "input": "", "output": answer}


def main() -> None:
    """Append valid QA records from JSON or JSONL input to an Alpaca file."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--qa", required=True, help="问答样本文件（JSON/JSONL），或 '-' 从标准输入读取"
    )
    parser.add_argument("--append-to", required=True, help="目标 Alpaca JSONL 文件（不存在则创建）")
    args = parser.parse_args()

    items = read_any(args.qa)
    if not items:
        print("未读取到任何问答条目（检查 --qa 输入）", file=sys.stderr)
        sys.exit(1)

    Path(args.append_to).parent.mkdir(parents=True, exist_ok=True)

    appended = 0
    with open(args.append_to, "a", encoding="utf-8") as fout:
        for obj in items:
            record = qa_to_alpaca(obj)
            fout.write(json.dumps(record, ensure_ascii=False) + "\n")
            appended += 1

    print(f"Done. appended={appended} -> {args.append_to}")


if __name__ == "__main__":
    main()
