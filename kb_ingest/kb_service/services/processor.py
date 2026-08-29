
import csv
import json
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import psycopg2

from kb_service.clients.llm import LLMClient
from kb_service.core.config import Config
from kb_service.prompts.manager import PromptManager, build_prompt_manager_from_env
from kb_service.prompts.manager import SchemaColumn
from kb_service.services.utils import flatten_row
from kb_service.services.vector_store import VectorStoreWriter


class DataProcessor:
    """High-level pipeline that flattens tabular data, rewrites rows, and writes to pgvector."""

    def __init__(self, config: Config, prompt_manager: Optional[PromptManager] = None, incremental: bool = False):
        self.config = config
        self.llm_client = LLMClient(config) if config.use_llm else None
        self.prompt_manager = prompt_manager or build_prompt_manager_from_env()
        self.vector_writer = VectorStoreWriter(config)
        self.processed_data: List[Dict] = []
        self.incremental = incremental  # 是否启用增量模式

        # 为本次处理创建时间戳目录
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.output_dir = Path("save") / self.timestamp
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 设置输出路径
        self.csv_path = str(self.output_dir / "processed_data.csv")
        self.txt_path = str(self.output_dir / "processed_data.txt")

        self._setup_logging()
        self._init_output_files()

    def _setup_logging(self) -> None:
        log_file = self.output_dir / "processing.log"
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.handlers.clear()

        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        self.logger = logging.getLogger(__name__)
        self.logger.info("日志已配置，输出目录: %s", self.output_dir)

    def _init_output_files(self) -> None:
        with open(self.csv_path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "source_table",
                    "source_id",
                    "original_data",
                    "rewritten_content",
                    "company_name",
                    "report_year",
                    "processed_time",
                ],
            )
            writer.writeheader()
        self.logger.info("✓ 初始化CSV文件: %s", self.csv_path)

        with open(self.txt_path, "w", encoding="utf-8") as fh:
            fh.write("=== Excel数据重写结果 ===\n")
            fh.write(f"处理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            fh.write(f"LLM模型: {self.config.llm_model}\n")
            fh.write("=" * 80 + "\n\n")
        self.logger.info("✓ 初始化TXT文件: %s", self.txt_path)

    def _convert_for_json(self, obj):
        if pd.isna(obj):
            return None
        if isinstance(obj, pd.Timestamp):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(obj, (pd.Timedelta, pd.Period)):
            return str(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="ignore")
        if isinstance(obj, Path):
            return str(obj)
        return obj

    def _prepare_row_dict(self, row_dict: dict) -> dict:
        return {key: self._convert_for_json(value) for key, value in row_dict.items()}

    def process_excel(self) -> None:
        self.logger.info("开始处理Excel文件: %s", self.config.excel_file_path)
        self.logger.info("LLM提供商: %s, 模型: %s", self.config.llm_provider, self.config.llm_model)

        xls = pd.ExcelFile(self.config.excel_file_path)
        total_sheets = len(xls.sheet_names)
        self.logger.info("发现 %s 个工作表", total_sheets)

        for idx, sheet_name in enumerate(xls.sheet_names, start=1):
            self.logger.info("[%s/%s] 处理工作表: %s", idx, total_sheets, sheet_name)
            self._process_sheet(xls, sheet_name)

        self._save_summary()
        if self.config.db:
            self._embed_and_store(incremental=self.incremental)
        self.logger.info("✅ 所有处理完成！")

    def _process_sheet(self, xls: pd.ExcelFile, sheet_name: str) -> None:
        df = pd.read_excel(xls, sheet_name=sheet_name)
        total_rows = len(df)
        self.logger.info("  共 %s 行数据", total_rows)

        processed_count = success_count = fail_count = 0
        schema = [SchemaColumn(name=str(col)) for col in df.columns]

        for start_idx in range(0, total_rows, self.config.batch_size):
            end_idx = min(start_idx + self.config.batch_size, total_rows)
            batch_df = df.iloc[start_idx:end_idx]
            self.logger.info("  处理批次 %s-%s/%s...", start_idx + 1, end_idx, total_rows)

            for row_idx, row in batch_df.iterrows():
                processed_count += 1
                progress = processed_count / total_rows * 100
                self.logger.info("  进度: %.1f%% (%s/%s)", progress, processed_count, total_rows)

                prev_count = len(self.processed_data)
                self._process_row(sheet_name, row_idx, row, schema)
                if len(self.processed_data) > prev_count:
                    success_count += 1
                else:
                    fail_count += 1

        self.logger.info("  工作表完成 - 成功: %s, 失败: %s", success_count, fail_count)

    def _process_row(
        self,
        sheet_name: str,
        row_idx: int,
        row: pd.Series,
        schema: List[SchemaColumn],
    ) -> None:
        row_dict = row.to_dict()
        if not self.config.use_llm:
            rewritten_text = flatten_row(row_dict, self.config)
            system_prompt = user_prompt = ""
        else:
            system_prompt, user_prompt = self.prompt_manager.get_prompt(
                sheet_name,
                row_dict,
                schema=schema,
            )
            rewritten_text = None
            for attempt in range(self.config.retry_times):
                try:
                    rewritten_text = self.llm_client.generate(user_prompt, system_prompt)
                    if rewritten_text:
                        break
                except Exception as exc:
                    self.logger.warning(
                        "    第 %s 行处理失败 (尝试 %s/%s): %s",
                        row_idx + 1,
                        attempt + 1,
                        self.config.retry_times,
                        exc,
                    )
                    if attempt < self.config.retry_times - 1:
                        time.sleep(self.config.retry_delay)
            if not rewritten_text and self.config.llm_fallback_to_flatten:
                self.logger.warning(
                    "    LLM 多次失败，第 %s 行改用扁平化结果",
                    row_idx + 1,
                )
                rewritten_text = flatten_row(row_dict, self.config)

        if not rewritten_text:
            self.logger.warning("    ✗ 第 %s 行处理失败", row_idx + 1)
            return

        clean_dict = self._prepare_row_dict(row_dict)
        company_name = clean_dict.get("公司名称", clean_dict.get("company_name", ""))
        report_year = clean_dict.get("报告年份", clean_dict.get("report_year", ""))

        result = {
            "source_table": sheet_name,
            "source_id": str(row_idx),
            "original_data": json.dumps(clean_dict, ensure_ascii=False),
            "rewritten_content": rewritten_text,
            "company_name": company_name,
            "report_year": str(report_year) if report_year else "",
            "processed_time": datetime.now().isoformat(),
        }

        self.processed_data.append(result)
        self._append_to_files(result)
        self.logger.info("    ✔ 第 %s 行处理成功并已写入文件", row_idx + 1)

    def _append_to_files(self, result: Dict) -> None:
        with open(self.csv_path, "a", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "source_table",
                    "source_id",
                    "original_data",
                    "rewritten_content",
                    "company_name",
                    "report_year",
                    "processed_time",
                ],
            )
            writer.writerow(result)

        with open(self.txt_path, "a", encoding="utf-8") as fh:
            title = f"[{result['source_table']} - ID:{result['source_id']}]"
            if result.get("company_name"):
                title += f" {result['company_name']}"
            fh.write(f"{title}\n")
            fh.write(f"{result['rewritten_content']}\n")
            fh.write("-" * 80 + "\n\n")

    def _save_summary(self) -> None:
        if not self.processed_data:
            self.logger.warning("没有数据需要汇总")
            return

        total_count = len(self.processed_data)
        sheets_processed: Dict[str, int] = {}
        for item in self.processed_data:
            sheet = item["source_table"]
            sheets_processed[sheet] = sheets_processed.get(sheet, 0) + 1

        with open(self.txt_path, "a", encoding="utf-8") as fh:
            fh.write("\n" + "=" * 80 + "\n")
            fh.write("处理完成汇总:\n")
            fh.write(f"总处理记录数: {total_count}\n")
            fh.write("各工作表处理数量:\n")
            for sheet, count in sheets_processed.items():
                fh.write(f"  - {sheet}: {count} 条\n")
            fh.write(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            fh.write("=" * 80 + "\n")

        self.logger.info("✓ 汇总信息已保存，共处理 %s 条记录", total_count)

    def _embed_and_store(self, incremental: bool = False) -> None:
        if not self.processed_data:
            self.logger.info("没有可入库的数据，跳过嵌入。")
            return

        items = []
        source_file = Path(self.config.excel_file_path).name
        for data in self.processed_data:
            original = data.get("original_data")
            parsed_original = original
            if isinstance(original, str):
                try:
                    parsed_original = json.loads(original)
                except Exception:
                    parsed_original = original

            if isinstance(parsed_original, dict):
                source_metadata = dict(parsed_original)
            else:
                source_metadata = {"original_data": parsed_original}
            source_metadata.setdefault("source_file", source_file)
            source_metadata.setdefault("source_sheet", data["source_table"])

            company_name = data.get("company_name")
            if not company_name and isinstance(parsed_original, dict):
                company_name = (
                    parsed_original.get("company_name(企业名称)")
                    or parsed_original.get("company_name")
                    or parsed_original.get("企业名称")
                )

            item = {
                "source_table": data["source_table"],
                "source_id": data["source_id"],
                "company_name": company_name or "",
                "report_year": data.get("report_year", ""),
                "rewritten_content": data["rewritten_content"],
                "original_data": source_metadata,
            }
            items.append(item)

        self.vector_writer.upsert(items, self.logger, incremental=incremental)

    # The following helper methods mirror the legacy script for recovery and maintenance flows
    # and will be progressively refactored into smaller services.

    def reembed_from_csv(self, csv_path: str = None, limit: int = None):
        import pandas as pd
        path = Path(csv_path or self.csv_path)
        if not path.exists():
            self.logger.error("CSV文件不存在：%s", path)
            return

        df = pd.read_csv(path)
        items = []

        for _, row in df.iterrows():
            if limit and len(items) >= limit:
                break
            items.append(
                {
                    "source_table": row.get("source_table", ""),
                    "source_id": row.get("source_id", ""),
                    "rewritten_content": row.get("rewritten_content", "") or "",
                    "company_name": row.get("company_name", "") or "",
                    "report_year": row.get("report_year", "") or "",
                    "original_data": json.loads(row.get("original_data", "{}") or "{}"),
                }
            )

        self.logger.info("准备恢复 %s 条数据", len(items))
        self.vector_writer.upsert(items, self.logger)
        self.logger.info("✓ CSV恢复完成")

    def _iter_txt_blocks(self, txt_path: Path):
        header_re = re.compile(r"^\[(?P<table>.+?)\s*-\s*ID:(?P<id>.+?)\]\s*(?P<company>.*)\s*$")
        sep_re = re.compile(r"^\-{40,}\s*$")

        current = None
        buf: List[str] = []

        with txt_path.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.rstrip("\n")
                if line.startswith("===") or line.startswith("处理时间:") or line.startswith("LLM模型:"):
                    continue
                if current is None:
                    match = header_re.match(line.strip())
                    if match:
                        current = match.groupdict()
                        buf = []
                    continue
                if sep_re.match(line):
                    if current and buf:
                        content = ("\n".join(buf)).strip()
                        yield (
                            current.get("table", ""),
                            current.get("id", ""),
                            current.get("company", "").strip(),
                            content,
                        )
                    current = None
                    buf = []
                else:
                    buf.append(line)

            if current is not None and buf:
                content = ("\n".join(buf)).strip()
                yield (
                    current.get("table", ""),
                    current.get("id", ""),
                    current.get("company", "").strip(),
                    content,
                )

    def reembed_from_txt(self, txt_path: str = None, limit: int = None):
        path = Path(txt_path or self.txt_path)
        if not path.exists():
            self.logger.error("TXT 不存在：%s", path)
            return

        self.logger.info("从TXT恢复向量：%s", path)
        items = []
        for table, sid, company, content in self._iter_txt_blocks(path):
            if not content:
                continue
            items.append(
                {
                    "source_table": table,
                    "source_id": sid,
                    "company_name": company,
                    "report_year": "",
                    "rewritten_content": content,
                    "original_data": "",
                }
            )
            if limit and len(items) >= limit:
                self.logger.info("达到限制 %s 条，停止读取", limit)
                break
        self.logger.info("准备恢复 %s 条数据", len(items))
        self.vector_writer.upsert(items, self.logger)
        self.logger.info("✓ TXT恢复完成")

    def check_recovery_status(self):
        status = {
            "csv_exists": False,
            "csv_records": 0,
            "txt_exists": False,
            "txt_records": 0,
        }

        csv_path = Path(self.csv_path)
        if csv_path.exists():
            status["csv_exists"] = True
            try:
                df = pd.read_csv(csv_path)
                status["csv_records"] = len(df)
            except Exception as exc:  # pragma: no cover - IO guard
                self.logger.error("读取CSV失败: %s", exc)

        txt_path = Path(self.txt_path)
        if txt_path.exists():
            status["txt_exists"] = True
            count = sum(1 for _ in self._iter_txt_blocks(txt_path))
            status["txt_records"] = count

        self.logger.info("=== 恢复数据状态 ===")
        self.logger.info("CSV文件: %s", "存在" if status["csv_exists"] else "不存在")
        if status["csv_exists"]:
            self.logger.info("  可恢复记录数: %s", status["csv_records"])
        self.logger.info("TXT文件: %s", "存在" if status["txt_exists"] else "不存在")
        if status["txt_exists"]:
            self.logger.info("  可恢复记录数: %s", status["txt_records"])
        return status

    def update_specific_records(self, updates: List[Dict]):
        if not updates:
            self.logger.warning("没有提供要更新的记录")
            return

        items = []
        for update in updates:
            source_table = update.get("source_table")
            source_id = update.get("source_id")
            content = update.get("content")
            if not source_table or not source_id or not content:
                self.logger.warning("缺少必要字段，跳过: %s", update)
                continue
            items.append(
                {
                    "source_table": source_table,
                    "source_id": source_id,
                    "rewritten_content": content,
                    "company_name": update.get("company_name", ""),
                    "report_year": update.get("report_year", ""),
                    "credit_no": update.get("credit_no", ""),
                    "origin_status": update.get("origin_status", ""),
                    "original_data": update.get("original_data", ""),
                }
            )

        self.vector_writer.upsert(items, self.logger)
        self.logger.info("✓ 指定记录更新完成，共处理 %s 条", len(items))

    def reprocess_by_filter(
        self,
        source_table: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
        company_name: Optional[str] = None,
        regenerate_content: bool = True,
    ):
        conn = psycopg2.connect(**self.config.db_config)
        cur = conn.cursor()

        conditions = []
        params: List = []

        if source_table:
            conditions.append("source_table = %s")
            params.append(source_table)
        if source_ids:
            conditions.append("source_id = ANY(%s)")
            params.append(source_ids)
        if company_name:
            conditions.append("company_name ILIKE %s")
            params.append(f"%{company_name}%")

        if not conditions:
            self.logger.error("必须指定至少一个筛选条件")
            return

        sql = f"""
            SELECT source_table, source_id, content, company_name, 
                   report_year, metadata
            FROM searchable_documents
            WHERE {' AND '.join(conditions)}
        """

        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()

        if not rows:
            self.logger.warning("未找到符合条件的记录")
            return

        self.logger.info("找到 %s 条记录", len(rows))

        items = []
        for row in rows:
            source_table, source_id, content, company_name, report_year, metadata = row
            if regenerate_content and self.config.use_llm:
                original_data = {}
                if metadata:
                    try:
                        original_data = json.loads(metadata)
                    except json.JSONDecodeError:
                        pass

                schema = [SchemaColumn(name=str(k)) for k in original_data.keys()]
                system_prompt, user_prompt = self.prompt_manager.get_prompt(
                    source_table,
                    original_data,
                    schema=schema,
                )

                new_content = None
                for attempt in range(self.config.retry_times):
                    try:
                        new_content = self.llm_client.generate(user_prompt, system_prompt)
                        if new_content:
                            break
                    except Exception as exc:
                        self.logger.warning("生成失败 (尝试 %s): %s", attempt + 1, exc)
                        if attempt < self.config.retry_times - 1:
                            time.sleep(self.config.retry_delay)

                if new_content:
                    content = new_content
                    self.logger.info("✓ 重新生成: %s-%s", source_table, source_id)
                else:
                    self.logger.warning("✗ 生成失败，使用原内容: %s-%s", source_table, source_id)

            items.append(
                {
                    "source_table": source_table,
                    "source_id": source_id,
                    "rewritten_content": content,
                    "company_name": company_name or "",
                    "report_year": report_year or "",
                    "original_data": metadata or "",
                }
            )

        self.vector_writer.upsert(items, self.logger)
        self.logger.info("✓ 处理完成，共更新 %s 条记录", len(items))

    def delete_records(self, source_table: str = None, source_ids: Optional[List[str]] = None):
        if not source_table or not source_ids:
            self.logger.error("必须指定表名和记录ID")
            return

        conn = psycopg2.connect(**self.config.db_config)
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM searchable_documents
            WHERE source_table = %s AND source_id = ANY(%s)
            """,
            (source_table, source_ids),
        )
        deleted = cur.rowcount
        conn.commit()
        conn.close()

        self.logger.info("✓ 已删除 %s 条记录", deleted)
