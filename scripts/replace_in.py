#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dataset_io import read_any


def detect_container(path: str) -> str:
    """Detect whether a file begins with a JSON array or JSONL record."""
    with open(path, "r", encoding="utf-8") as f:
        while True:
            ch = f.read(1)
            if not ch:
                return "json"  # empty -> treat as json
            if ch.isspace():
                continue
            return "json" if ch == "[" else "jsonl"


def parse_replace(spec: str) -> tuple[str, str]:
    """Split one literal replacement argument at its first arrow marker."""
    # format: old=>new
    if "=>" not in spec:
        raise ValueError(f"--replace 参数格式应为 old=>new, 但收到: {spec}")
    old, new = spec.split("=>", 1)
    return old, new


def apply_rules(val: str, rules: list[tuple[str, str]]) -> str:
    """Apply ordered literal replacements to one string value."""
    out = val
    for old, new in rules:
        out = out.replace(old, new)
    return out


def main() -> None:
    """Replace selected string fields while preserving JSON container format."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", required=True, help="输入 JSON/JSONL 文件")
    parser.add_argument(
        "--out", dest="out_path", required=True, help="输出文件路径（容器类型随输入保持）"
    )
    parser.add_argument("--field", default="output", help="要替换内容的字段名（默认 output）")
    parser.add_argument(
        "--replace", action="append", required=True, help="替换规则：old=>new，可多次传入"
    )
    args = parser.parse_args()

    container = detect_container(args.in_path)  # "json" or "jsonl"
    rules = [parse_replace(r) for r in args.replace]

    items = read_any(args.in_path)
    if not items:
        print("未读取到任何条目（请检查输入文件格式为 JSON 数组或 JSONL）", file=sys.stderr)
        sys.exit(1)

    Path(args.out_path).parent.mkdir(parents=True, exist_ok=True)

    changed = 0
    # Apply replacements
    for obj in items:
        if args.field in obj and isinstance(obj[args.field], str):
            new_val = apply_rules(obj[args.field], rules)
            if new_val != obj[args.field]:
                obj[args.field] = new_val
                changed += 1

    # Write back preserving container
    if container == "json":
        with open(args.out_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
            f.write("\n")
    else:
        with open(args.out_path, "w", encoding="utf-8") as f:
            for obj in items:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    print(f"Done. total={len(items)}, changed={changed}, out={args.out_path}, format={container}")


if __name__ == "__main__":
    main()
