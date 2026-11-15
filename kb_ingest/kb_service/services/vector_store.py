import json
from contextlib import closing
import logging
from typing import Iterable, List, Optional

import psycopg2
from pgvector.psycopg2 import register_vector

from kb_service.clients.embedding import EmbeddingClient
from kb_service.core.config import Config
from kb_service.services.utils import compute_content_hash


class VectorStoreWriter:
    """Handles embedding generation and upserts into pgvector-backed tables."""

    def __init__(self, config: Config, embedding_client: Optional[EmbeddingClient] = None):
        self.config = config
        self._owns_embedding_client = embedding_client is None
        self.embedding_client = (
            embedding_client if embedding_client is not None else EmbeddingClient(config)
        )
        self.logger = logging.getLogger(__name__)

    def upsert(
        self,
        items: Iterable[dict],
        logger: Optional[logging.Logger] = None,
        incremental: bool = False,
    ) -> int:
        items = list(items)
        if not items:
            (logger or self.logger).info("没有可嵌入的数据，跳过。")
            return 0

        log = logger or self.logger

        # 增量模式：过滤出需要处理的数据
        if incremental:
            items = self._filter_changed_items(items, log)
            if not items:
                log.info("增量模式：所有数据均未变化，跳过处理。")
                return 0
            log.info("增量模式：检测到 %s 条数据需要更新", len(items))

        vector_dim = self.embedding_client.dimension
        if vector_dim <= 0:
            probe_vec = self.embedding_client.embed_texts(["__probe__"])[0]
            vector_dim = len(probe_vec)
            self.embedding_client.dimension = vector_dim

        with closing(psycopg2.connect(**self.config.db_config)) as conn, conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            conn.commit()
            register_vector(conn)

            self._ensure_table(conn, vector_dim, log)

            batch_size = 32
            total = 0
            for start in range(0, len(items), batch_size):
                batch = items[start : start + batch_size]
                texts = [item["rewritten_content"] for item in batch]
                embeddings = self.embedding_client.embed_texts(texts)
                if len(embeddings) != len(batch):
                    raise ValueError("Embedding count must match batch size")

                for idx, embedding in enumerate(embeddings):
                    if len(embedding) != vector_dim:
                        raise ValueError(
                            f"第 {start + idx + 1} 条嵌入维度为 {len(embedding)}，与模型维度 {vector_dim} 不一致。"
                        )

                for item, embedding in zip(batch, embeddings):
                    emb_list = self._to_float_list(embedding)
                    meta = self._serialize_metadata(item.get("original_data"))

                    # 计算内容哈希
                    content_hash = compute_content_hash(item.get("original_data") or {})

                    cur.execute(
                        """
                        INSERT INTO searchable_documents
                          (source_table, source_id, content, embedding,
                            company_name, report_year, credit_no, origin_status,
                            metadata, content_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_table, source_id)
                          DO UPDATE SET
                            content       = EXCLUDED.content,
                            embedding     = EXCLUDED.embedding,
                            company_name  = EXCLUDED.company_name,
                            report_year   = EXCLUDED.report_year,
                            credit_no     = EXCLUDED.credit_no,
                            origin_status = EXCLUDED.origin_status,
                            metadata      = EXCLUDED.metadata,
                            content_hash  = EXCLUDED.content_hash,
                            created_at    = CURRENT_TIMESTAMP;
                        """,
                        (
                            item["source_table"],
                            item["source_id"],
                            item["rewritten_content"],
                            emb_list,
                            self._maybe_text(item.get("company_name")),
                            self._maybe_text(item.get("report_year")),
                            self._maybe_text(item.get("credit_no")),
                            self._maybe_text(item.get("origin_status")),
                            meta,
                            content_hash,
                        ),
                    )
                conn.commit()
                total += len(batch)

        log.info("嵌入并入库完成，共处理 %s 条", total)
        return total

    def _ensure_table(self, conn, vector_dim: int, log: logging.Logger) -> None:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.searchable_documents');")
            table_exists = cur.fetchone()[0] is not None

            text_cols = [
                "source_table",
                "source_id",
                "content",
                "company_name",
                "report_year",
                "credit_no",
                "origin_status",
                "metadata",
            ]

            if not table_exists:
                cur.execute(
                    f"""
                    CREATE TABLE searchable_documents (
                        id BIGSERIAL PRIMARY KEY,
                        source_table  TEXT,
                        source_id     TEXT,
                        content       TEXT,
                        embedding     vector({vector_dim}),
                        company_name  TEXT,
                        report_year   TEXT,
                        credit_no     TEXT,
                        origin_status TEXT,
                        metadata      TEXT,
                        content_hash  TEXT DEFAULT '',
                        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(source_table, source_id)
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_sd_source_pair
                    ON searchable_documents (source_table, source_id);
                    """
                )
                conn.commit()
                return

            for col in text_cols:
                cur.execute(
                    f"ALTER TABLE searchable_documents ADD COLUMN IF NOT EXISTS {col} TEXT;"
                )

            cur.execute(
                """
                ALTER TABLE searchable_documents
                ADD COLUMN IF NOT EXISTS content_hash TEXT DEFAULT '';
                """
            )
            cur.execute(
                """
                ALTER TABLE searchable_documents
                ALTER COLUMN content_hash SET DEFAULT '';
                """
            )
            cur.execute(
                """
                ALTER TABLE searchable_documents
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
                """
            )
            cur.execute(
                "ALTER TABLE searchable_documents ADD COLUMN IF NOT EXISTS "
                f"embedding vector({vector_dim});"
            )
            conn.commit()

            cur.execute(
                """
                UPDATE searchable_documents
                SET content_hash = ''
                WHERE content_hash IS NULL;
                """
            )
            conn.commit()

            cur.execute(
                """
                SELECT atttypmod AS dim
                FROM pg_attribute
                WHERE attrelid = 'searchable_documents'::regclass
                  AND attname = 'embedding';
                """
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("表存在但未检测到 embedding 列，请检查表结构。")
            table_dim = int(row[0])

            if table_dim != vector_dim:
                log.warning(
                    "检测到表向量维度=%s 与 模型维度=%s 不一致，准备处理...", table_dim, vector_dim
                )
                cur.execute("SELECT COUNT(*) FROM searchable_documents;")
                rowcount = cur.fetchone()[0]
                if rowcount == 0:
                    log.info("表为空，将自动调整 embedding 列维度以匹配模型。")
                    cur.execute(
                        "ALTER TABLE searchable_documents ALTER COLUMN "
                        f"embedding TYPE vector({vector_dim});"
                    )
                    conn.commit()
                else:
                    raise RuntimeError(
                        "searchable_documents 已有数据且向量维度与模型不一致，请先迁移或手动调整表结构。"
                    )

            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sd_source_pair
                ON searchable_documents (source_table, source_id);
                """
            )
            conn.commit()

    def _serialize_metadata(self, raw_meta) -> Optional[str]:
        if raw_meta is None:
            return None
        if isinstance(raw_meta, str):
            return raw_meta
        return json.dumps(raw_meta, ensure_ascii=False, default=str)

    def _maybe_text(self, value) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _to_float_list(self, embedding) -> List[float]:
        if hasattr(embedding, "tolist"):
            embedding = embedding.tolist()
        if (
            isinstance(embedding, (list, tuple))
            and embedding
            and isinstance(embedding[0], (list, tuple))
        ):
            embedding = [x for row in embedding for x in row]
        return [float(x) for x in embedding]

    def _filter_changed_items(self, items: List[dict], log: logging.Logger) -> List[dict]:
        """
        过滤出内容发生变化的数据项

        Args:
            items: 待处理的数据项列表
            log: 日志对象

        Returns:
            需要更新的数据项列表
        """
        if not items:
            return []

        # 批量查询现有记录的哈希值
        conn = psycopg2.connect(**self.config.db_config)
        try:
            with conn.cursor() as cur:
                # 构建查询条件
                conditions = [(item["source_table"], item["source_id"]) for item in items]

                # 批量查询
                query = """
                    SELECT source_table, source_id, content_hash
                    FROM searchable_documents
                    WHERE (source_table, source_id) IN %s
                """
                cur.execute(query, (tuple(conditions),))
                existing_hashes = {(row[0], row[1]): row[2] for row in cur.fetchall()}

                log.info("从数据库查询到 %s 条现有记录的哈希", len(existing_hashes))

        finally:
            conn.close()

        # 过滤变化的数据
        changed_items = []
        skipped_count = 0

        for item in items:
            source_table = item["source_table"]
            source_id = item["source_id"]
            original_data = item.get("original_data") or {}

            # 计算新数据的哈希
            new_hash = compute_content_hash(original_data)

            # 查找现有哈希
            key = (source_table, source_id)
            existing_hash = existing_hashes.get(key)

            if existing_hash is None:
                # 新记录
                changed_items.append(item)
                log.debug("新记录: %s/%s", source_table, source_id)
            elif existing_hash != new_hash:
                # 内容变化
                changed_items.append(item)
                log.debug(
                    "内容变化: %s/%s (旧哈希: %s, 新哈希: %s)",
                    source_table,
                    source_id,
                    existing_hash[:8],
                    new_hash[:8],
                )
            else:
                # 内容未变化，跳过
                skipped_count += 1
                log.debug("跳过未变化: %s/%s", source_table, source_id)

        log.info("增量检测结果: 需更新 %s 条, 跳过 %s 条", len(changed_items), skipped_count)

        return changed_items

    def close(self) -> None:
        if self._owns_embedding_client:
            self.embedding_client.close()
