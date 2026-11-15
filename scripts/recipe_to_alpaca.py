#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dataset_io import read_any


def is_recipe(record: Dict[str, Any]) -> bool:
    field_names = {k.lower() for k in record.keys()}
    return ("recipeingredient" in field_names) or ("recipeinstructions" in field_names)


def build_instruction(keywords, name=None) -> str:
    """由 keywords 生成问句；无 keywords 时退化到菜名问句"""
    if keywords is not None:
        keywords = [str(keyword).strip() for keyword in keywords if str(keyword).strip()]
    if keywords:
        return f"根据关键词（{'、'.join(keywords)}），列出所需配料并给出详细做法。"
    return f"如何制作『{name}』？" if name else "这道菜需要哪些配料并如何制作？"


def to_lines(value: Any) -> List[str]:
    """把列表/标量转成行列表；对嵌套列表用 '、' 拼接"""
    if value is None:
        return []
    if isinstance(value, list):
        return [("、".join(map(str, x)) if isinstance(x, (list, tuple)) else str(x)) for x in value]
    return [str(value)]


def build_output(ingredients, steps) -> str:
    ingredient_lines = to_lines(ingredients)
    step_lines = to_lines(steps)
    out = []
    if ingredient_lines:
        out.append("【配料】")
        out.extend(ingredient_lines)
    if step_lines:
        out.append("")  # 空行
        out.append("【做法】")
        out.extend([f"{i+1}. {s}" for i, s in enumerate(step_lines)])
    return "\n".join(out).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", required=True, help="输入 JSON/JSONL 文件")
    parser.add_argument("--out", dest="out_path", required=True, help="输出 Alpaca JSONL 文件")
    args = parser.parse_args()

    items = read_any(args.in_path)
    if not items:
        print("未读取到有效条目（请检查输入文件格式是否为 JSON 数组或 JSONL）", file=sys.stderr)
        sys.exit(1)

    Path(args.out_path).parent.mkdir(parents=True, exist_ok=True)

    kept = 0
    with open(args.out_path, "w", encoding="utf-8") as fout:
        for record in items:
            if not is_recipe(record):
                continue
            instruction = build_instruction(
                record.get("keywords"), record.get("name") or record.get("dish")
            )
            input_text = str(record.get("description") or "")
            output_text = build_output(
                record.get("recipeIngredient", record.get("ingredients")),
                record.get("recipeInstructions", record.get("steps")),
            )
            record_output = {"instruction": instruction, "input": input_text, "output": output_text}
            fout.write(json.dumps(record_output, ensure_ascii=False) + "\n")
            kept += 1

    print(f"Done. total={len(items)}, wrote={kept}, out={args.out_path}")


if __name__ == "__main__":
    main()
