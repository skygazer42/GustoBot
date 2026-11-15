import hashlib
import json
import re
from datetime import date, datetime
from typing import Dict, Mapping, Union

import pandas as pd

from kb_service.core.config import Config


def is_missing_value(value: object) -> bool:
    """Recognize scalar database nulls without coercing arrays or containers."""
    return value is None or (pd.api.types.is_scalar(value) and bool(pd.isna(value)))


def flatten_row(row: Mapping[str, object], config: Config) -> str:
    """Convert a row dict into a flattened `key: value` string for embedding."""

    flat_pairs: list[str] = []
    seen: Dict[str, object] = {}

    for key, value in row.items():
        if key is None:
            continue
        normalized_key = str(key).strip().replace("（", "(").replace("）", ")")
        while True:
            stripped = re.sub(r"\s*\([^()]*\)\s*$", "", normalized_key)
            if stripped == normalized_key:
                break
            normalized_key = stripped
        if re.match(r"^Unnamed[:\s]", normalized_key, flags=re.I):
            continue

        if normalized_key not in seen or (not _nonempty(seen[normalized_key]) and _nonempty(value)):
            if isinstance(value, (pd.Timestamp, datetime, date)):
                value = pd.Timestamp(value).isoformat(sep=" ", timespec="seconds")
            seen[normalized_key] = value

    for normalized_key, value in seen.items():
        if is_missing_value(value):
            continue
        value_str = str(value).strip()
        if value_str in {"", "-", "nan", "NaN"}:
            continue
        flat_pairs.append(f"{normalized_key}{config.flat_kv_sep}{value_str}")

    flat_text = config.flat_sep.join(flat_pairs)
    if config.flat_max_len > 0 and len(flat_text) > config.flat_max_len:
        flat_text = flat_text[: config.flat_max_len]
    return flat_text


def _nonempty(value: object) -> bool:
    if is_missing_value(value):
        return False
    return str(value).strip() not in {"", "-", "nan", "NaN", "None", "null"}


def compute_content_hash(data: Union[Dict, str], algorithm: str = "md5") -> str:
    """
    计算数据的哈希值，用于检测内容变化

    Args:
        data: 字典或字符串数据
        algorithm: 哈希算法，支持 'md5', 'sha256'

    Returns:
        哈希值的十六进制字符串
    """
    if isinstance(data, dict):
        # 将字典转为稳定的JSON字符串（排序key）
        content = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    else:
        content = str(data)

    # 计算哈希
    if algorithm == "sha256":
        hasher = hashlib.sha256()
    else:
        hasher = hashlib.md5(usedforsecurity=False)

    hasher.update(content.encode("utf-8"))
    return hasher.hexdigest()
