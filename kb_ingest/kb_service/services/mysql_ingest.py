import logging
import re
import time
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import create_engine
from sqlalchemy.sql.elements import TextClause

from kb_service.clients.llm import LLMClient
from kb_service.core.config import Config
from kb_service.prompts.manager import PromptManager, SchemaColumn, build_prompt_manager_from_env
from kb_service.schemas.ingest import MySQLIngestRequest
from kb_service.services.utils import flatten_row, is_missing_value
from kb_service.services.vector_store import VectorStoreWriter


_FILTER_TOKEN = re.compile(
    r"\s+|--|/\*|"
    r"'(?:''|\\.|[^'\\])*'|\"(?:\"\"|\\.|[^\"\\])*\"|"
    r"`[\w$]+`|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|"
    r"[^\W\d]\w*|<=>|<=|>=|<>|!=|[=<>+*/%(),.\-]"
)
_FILTER_KEYWORDS = {
    "AND",
    "OR",
    "XOR",
    "NOT",
    "IN",
    "BETWEEN",
    "IS",
    "NULL",
    "TRUE",
    "FALSE",
    "LIKE",
    "REGEXP",
    "RLIKE",
    "ESCAPE",
    "BINARY",
    "CASE",
    "WHEN",
    "THEN",
    "ELSE",
    "END",
    "AS",
    "CHAR",
    "SIGNED",
    "UNSIGNED",
    "DECIMAL",
    "DATETIME",
    "TIME",
    "JSON",
}
_FILTER_FUNCTIONS = {
    "ABS",
    "ROUND",
    "CEIL",
    "CEILING",
    "FLOOR",
    "LOWER",
    "UPPER",
    "LENGTH",
    "CHAR_LENGTH",
    "TRIM",
    "LTRIM",
    "RTRIM",
    "CONCAT",
    "SUBSTRING",
    "REPLACE",
    "COALESCE",
    "IFNULL",
    "NULLIF",
    "DATE",
    "YEAR",
    "MONTH",
    "DAY",
    "DAYOFMONTH",
    "DATE_FORMAT",
    "DATEDIFF",
    "JSON_EXTRACT",
    "JSON_UNQUOTE",
    "CAST",
    "CHAR",
}
_STATEMENT_KEYWORDS = {
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "UNION",
    "INTO",
    "OUTFILE",
    "DUMPFILE",
    "LOAD",
    "CALL",
    "SET",
    "GRANT",
    "REVOKE",
    "SHOW",
    "WITH",
}
FilterValue = Union[str, int, float]


def _parameterize_filter(expression: str) -> Tuple[str, Dict[str, FilterValue]]:
    """Retain scalar SQL expressions, binding literals and allowing pure functions only.

    Every emitted token is reconstructed from an operator/keyword allowlist or a
    quoted identifier. Statements, subqueries, comments and session variables are
    rejected before a connection executes the query.
    """
    tokens = []
    position = 0
    while position < len(expression):
        match = _FILTER_TOKEN.match(expression, position)
        if match is None or match.group() in {"--", "/*"}:
            raise ValueError("Unsupported token in MySQL WHERE filter")
        token = match.group()
        position = match.end()
        if not token.isspace():
            tokens.append(token)
    if not tokens:
        raise ValueError("MySQL WHERE filter cannot be empty")

    sql_tokens = []
    parameters: Dict[str, FilterValue] = {}
    depth = 0
    type_precision_depth: Optional[int] = None
    escapes = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a"}

    def decode_escape(match: re.Match[str]) -> str:
        character = match.group(1)
        return escapes.get(character, character)

    for index, token in enumerate(tokens):
        upper = token.upper()
        followed_by_parenthesis = index + 1 < len(tokens) and tokens[index + 1] == "("
        if followed_by_parenthesis and index > 0 and tokens[index - 1] == ".":
            raise ValueError("Schema-qualified functions are not allowed in a MySQL WHERE filter")
        if token[0] in {"'", '"'}:
            quote = token[0]
            value = re.sub(r"\\(.)", decode_escape, token[1:-1]).replace(quote * 2, quote)
            key = f"filter_{len(parameters)}"
            parameters[key] = value
            sql_tokens.append(f":{key}")
        elif token[0].isdigit() or (token[0] == "." and len(token) > 1):
            if type_precision_depth == depth:
                if not token.isdigit():
                    raise ValueError("CAST precision must be a positive integer")
                sql_tokens.append(str(int(token)))
                continue
            key = f"filter_{len(parameters)}"
            parameters[key] = float(token) if any(c in token for c in ".eE") else int(token)
            sql_tokens.append(f":{key}")
        elif token == "(":
            depth += 1
            sql_tokens.append(token)
        elif token == ")":
            if type_precision_depth == depth:
                type_precision_depth = None
            depth -= 1
            if depth < 0:
                raise ValueError("Unbalanced MySQL WHERE parentheses")
            sql_tokens.append(token)
        elif upper in _STATEMENT_KEYWORDS:
            raise ValueError("Statements and subqueries are not allowed in a MySQL WHERE filter")
        elif followed_by_parenthesis and upper not in {
            "IN",
            "NOT",
            "AND",
            "OR",
            "XOR",
            "WHEN",
            "THEN",
            "ELSE",
        }:
            is_cast_type = (
                upper in {"DECIMAL", "CHAR"} and index > 0 and tokens[index - 1].upper() == "AS"
            )
            if is_cast_type:
                type_precision_depth = depth + 1
            elif upper not in _FILTER_FUNCTIONS:
                raise ValueError(f"Unsupported function in MySQL WHERE filter: {token}")
            sql_tokens.append(upper)
        elif upper in _FILTER_KEYWORDS:
            sql_tokens.append(upper)
        elif token.startswith("`"):
            sql_tokens.append(token)
        elif token[0].isalpha() or token[0] == "_":
            sql_tokens.append(f"`{token}`")
        else:
            sql_tokens.append(token)
    if depth:
        raise ValueError("Unbalanced MySQL WHERE parentheses")
    return " ".join(sql_tokens), parameters


class MySQLIngestor:
    """Ingests MySQL rows, rewrites or flattens them, and writes embeddings."""

    def __init__(self, config: Config, prompt_manager: Optional[PromptManager] = None):
        self.config = config
        self.prompt_manager = prompt_manager or build_prompt_manager_from_env()
        self.llm_client: Optional[LLMClient] = None
        self.vector_writer = VectorStoreWriter(config)
        self.logger = logging.getLogger(__name__)

    def ingest(self, request: MySQLIngestRequest) -> Dict[str, int]:
        engine = create_engine(request.connection_url)
        total_rows = 0
        embedded_rows = 0

        try:
            with engine.connect() as conn:
                schema = self._fetch_schema(conn, request.table)
                query = self._build_query(request)

                chunks = pd.read_sql_query(query, conn, chunksize=request.chunk_size)
                if isinstance(chunks, pd.DataFrame):
                    embedded_rows += self._process_chunk(chunks, schema, request)
                    total_rows += len(chunks)
                else:
                    for chunk in chunks:
                        total_rows += len(chunk)
                        embedded_rows += self._process_chunk(chunk, schema, request)
        finally:
            engine.dispose()

        self.logger.info("MySQL ingest完成: 共读取 %s 条, 写入 %s 条", total_rows, embedded_rows)
        return {"rows_read": total_rows, "rows_embedded": embedded_rows}

    def _process_chunk(
        self,
        chunk: pd.DataFrame,
        schema: List[SchemaColumn],
        request: MySQLIngestRequest,
    ) -> int:
        if chunk.empty:
            return 0

        items: List[Dict] = []
        template_key = request.prompt_key or request.table
        override_template = request.prompt_template
        effective_schema = schema or [SchemaColumn(name=str(col)) for col in chunk.columns]

        for idx, row in chunk.iterrows():
            row_dict = {
                key: None if is_missing_value(value) else value
                for key, value in row.to_dict().items()
            }
            merged_meta = {**row_dict, **request.extra_metadata}

            source_id = self._extract_identifier(row_dict, request.id_column, idx)
            company_name = self._extract_optional_field(row_dict, request.company_field)
            report_year = self._extract_optional_field(row_dict, request.report_year_field)

            content: Optional[str]
            if request.mode == "flatten":
                content = flatten_row(merged_meta, self.config)
            else:
                system_prompt, user_prompt = self.prompt_manager.get_prompt(
                    template_key,
                    merged_meta,
                    schema=effective_schema,
                    override_template=override_template,
                    context_table_name=request.table,
                )
                content = self._generate_with_retry(user_prompt, system_prompt)
                if not content:
                    self.logger.warning("跳过第 %s 行，LLM 未返回内容", idx)
                    continue

            items.append(
                {
                    "source_table": request.table,
                    "source_id": source_id,
                    "rewritten_content": content,
                    "company_name": company_name or "",
                    "report_year": report_year or "",
                    "original_data": merged_meta,
                }
            )

        if not items:
            return 0

        return self.vector_writer.upsert(items, self.logger)

    def _generate_with_retry(self, prompt: str, system_prompt: str) -> Optional[str]:
        if self.llm_client is None:
            self.llm_client = LLMClient(self.config)
        for attempt in range(self.config.retry_times):
            try:
                content = self.llm_client.generate(prompt, system_prompt)
                if content:
                    return content
            except Exception as exc:
                self.logger.warning(
                    "LLM 生成失败 (尝试 %s/%s): %s", attempt + 1, self.config.retry_times, exc
                )
                if attempt < self.config.retry_times - 1:
                    time.sleep(self.config.retry_delay)
        return None

    def _extract_identifier(self, row: Dict, id_column: Optional[str], fallback_idx: int) -> str:
        if id_column is None:
            return str(fallback_idx)
        value = row[id_column]
        if value is None:
            raise ValueError(f"Configured identifier column {id_column!r} cannot be null")
        return str(value)

    def _extract_optional_field(self, row: Dict, field_name: Optional[str]) -> Optional[str]:
        if field_name is None:
            return None
        value = row[field_name]
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _build_query(self, request: MySQLIngestRequest) -> TextClause:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", request.table):
            raise ValueError("table must be a simple SQL identifier")
        base = f"SELECT * FROM `{request.table}`"
        parameters: Dict[str, FilterValue] = {}
        if request.where:
            condition, parameters = _parameterize_filter(request.where)
            base += f" WHERE {condition}"
        if request.limit is not None:
            base += " LIMIT :row_limit"
            parameters["row_limit"] = request.limit
        return text(base).bindparams(**parameters)

    def _fetch_schema(self, conn, table: str) -> List[SchemaColumn]:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            raise ValueError("table must be a simple SQL identifier")
        result = conn.execute(text(f"SHOW FULL COLUMNS FROM `{table}`"))
        schema = []
        for mapping in result.mappings():
            schema.append(
                SchemaColumn(
                    name=mapping["Field"],
                    data_type=mapping["Type"],
                    comment=mapping["Comment"],
                )
            )
        return schema

    def close(self) -> None:
        try:
            self.vector_writer.close()
        finally:
            if self.llm_client is not None:
                self.llm_client.close()
