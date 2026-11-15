import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Dict, Iterable, Mapping, Optional, Tuple, Union


@dataclass
class SchemaColumn:
    name: str
    data_type: Optional[str] = None
    comment: Optional[str] = None


@dataclass
class PromptTemplate:
    system: str
    user: str


DEFAULT_SYSTEM_PROMPT = (
    "你是一名专业的数据描述专家，负责将结构化数据转换为通顺的自然语言摘要，以便进行语义搜索。"
)

DEFAULT_USER_TEMPLATE = Template(
    """请基于以下信息生成一段完整、通顺、便于检索的描述，并直接输出最终文本：

- 数据来源表：${table_name}
- 表字段说明：${columns}
- 该行数据（键值对）：
${row_flat}

请遵循：
1. 使用一段自然语言描述所有关键信息，可适当合并同类字段；
2. 忽略空值、无意义或缺失的字段，不要输出“未知/暂无”等词；
3. 如果包含时间或数值，请保留原始含义；
4. 输出必须是单段文本，不要列举或解释要求。
"""
)


class PromptManager:
    """Prompt registry with generic fallback and optional overrides."""

    def __init__(
        self,
        templates: Optional[Mapping[str, Union[Mapping[str, str], str]]] = None,
        config_path: Optional[str] = None,
    ) -> None:
        loaded_templates = self._load_from_path(config_path) if config_path else {}
        if templates:
            loaded_templates.update(templates)

        self.default_template = PromptTemplate(
            system=DEFAULT_SYSTEM_PROMPT,
            user=DEFAULT_USER_TEMPLATE.template,
        )
        self.table_templates: Dict[str, PromptTemplate] = {}

        for name, template in loaded_templates.items():
            self.register_template(name, template)

    def register_template(self, key: str, template: Union[Mapping[str, str], str]) -> None:
        self.table_templates[key] = self._coerce_template(template)

    def get_prompt(
        self,
        table_name: str,
        row_data: Mapping[str, object],
        schema: Optional[Iterable[SchemaColumn]] = None,
        override_template: Optional[Union[Mapping[str, str], str]] = None,
        context_table_name: Optional[str] = None,
    ) -> Tuple[str, str]:
        template = self._resolve_template(table_name, override_template)
        context = {
            "table_name": context_table_name or table_name,
            "columns": self._format_schema(schema),
            "row_flat": self._format_row_data(row_data),
            "row_json": json.dumps(self._serialize_row_data(row_data), ensure_ascii=False),
        }
        user_prompt = Template(template.user).safe_substitute(context)
        return template.system, user_prompt

    def _resolve_template(
        self,
        table_name: str,
        override: Optional[Union[Mapping[str, str], str]],
    ) -> PromptTemplate:
        if override is not None:
            return self._coerce_template(override)
        if table_name in self.table_templates:
            return self.table_templates[table_name]
        return self.default_template

    def _coerce_template(self, template: Union[Mapping[str, str], str]) -> PromptTemplate:
        if isinstance(template, str):
            return PromptTemplate(system=DEFAULT_SYSTEM_PROMPT, user=template)
        system = template.get("system", DEFAULT_SYSTEM_PROMPT)
        user = template.get("user", DEFAULT_USER_TEMPLATE.template)
        return PromptTemplate(system=system, user=user)

    def _format_row_data(self, row_data: Mapping[str, object]) -> str:
        lines = []
        for key, value in row_data.items():
            if value in (None, "", "-", "nan", "NaN"):
                continue
            # 处理datetime对象
            if isinstance(value, datetime):
                value = value.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"- {key}: {value}")
        return "\n".join(lines) if lines else "(空记录)"

    def _serialize_row_data(self, row_data: Mapping[str, object]) -> Mapping[str, object]:
        """序列化row_data，处理datetime等不可序列化的对象"""
        serialized: Dict[str, object] = {}
        for key, value in row_data.items():
            if isinstance(value, datetime):
                serialized[key] = value.strftime("%Y-%m-%d %H:%M:%S")
            else:
                serialized[key] = value
        return serialized

    def _format_schema(self, schema: Optional[Iterable[SchemaColumn]]) -> str:
        if not schema:
            return "(未提供字段说明)"
        parts = []
        for col in schema:
            comment = f"，说明：{col.comment}" if col.comment else ""
            dtype = f"类型：{col.data_type}" if col.data_type else ""
            meta = "，".join(filter(None, [dtype, comment]))
            parts.append(f"{col.name}{'（' + meta + '）' if meta else ''}")
        return "；".join(parts)

    def _load_from_path(self, path: str) -> Dict[str, Union[Mapping[str, str], str]]:
        file_path = Path(path)
        if not file_path.exists():
            return {}
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Prompt config file must be a JSON object")
            return data
        except (OSError, ValueError) as exc:  # pragma: no cover
            raise RuntimeError(f"Failed to load prompt config: {path}") from exc


def build_prompt_manager_from_env() -> PromptManager:
    config_path = os.getenv("PROMPT_CONFIG_PATH")
    return PromptManager(config_path=config_path)
