"""
通用向量存储服务 - 支持任意表结构

核心改进：
1. 移除硬编码的字段（company_name, report_year等）
2. 所有原始字段存储在 JSONB metadata 中
3. 支持任意表结构，无需修改代码
"""

import json
from contextlib import closing
import logging
from typing import Iterable, List, Optional

import psycopg2
from pgvector.psycopg2 import register_vector

from kb_service.clients.embedding import EmbeddingClient
from kb_service.core.config import Config


class VectorStoreWriterGeneric:
    """通用向量存储 - 支持任意表结构"""

    def __init__(self, config: Config, embedding_client: Optional[EmbeddingClient] = None):
        self.config = config
        self._owns_embedding_client = embedding_client is None
        self.embedding_client = (
            embedding_client if embedding_client is not None else EmbeddingClient(config)
        )
        self.logger = logging.getLogger(__name__)

    def upsert(self, items: Iterable[dict], logger: Optional[logging.Logger] = None) -> int:
        """
        插入或更新向量数据

        Args:
            items: 数据项列表，每项包含：
                - source_table: 来源表名
                - source_id: 原始记录ID
                - rewritten_content: 重写后的文本
                - original_data: 原始数据（任意字段）
            logger: 日志记录器

        Returns:
            处理的记录数
        """
        items = list(items)
        if not items:
            (logger or self.logger).info("没有可嵌入的数据，跳过。")
            return 0

        log = logger or self.logger

        # 检测向量维度
        vector_dim = self.embedding_client.dimension
        if vector_dim <= 0:
            probe_vec = self.embedding_client.embed_texts(["__probe__"])[0]
            vector_dim = len(probe_vec)
            self.embedding_client.dimension = vector_dim

        # 连接数据库
        with closing(psycopg2.connect(**self.config.db_config)) as conn, conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            conn.commit()
            register_vector(conn)

            # 确保表存在
            self._ensure_table(conn, vector_dim, log)

            # 批量处理
            batch_size = 32
            total = 0
            for start in range(0, len(items), batch_size):
                batch = items[start : start + batch_size]
                texts = [item["rewritten_content"] for item in batch]
                embeddings = self.embedding_client.embed_texts(texts)
                if len(embeddings) != len(batch):
                    raise ValueError("Embedding count must match batch size")

                # 验证维度
                for idx, embedding in enumerate(embeddings):
                    if len(embedding) != vector_dim:
                        raise ValueError(
                            f"第 {start + idx + 1} 条嵌入维度为 {len(embedding)}，与模型维度 {vector_dim} 不一致。"
                        )

                # 插入数据
                for item, embedding in zip(batch, embeddings):
                    emb_list = self._to_float_list(embedding)

                    # 将所有原始数据序列化为 JSON
                    meta = self._serialize_metadata(item.get("original_data"))

                    cur.execute(
                        """
                        INSERT INTO searchable_documents
                          (source_table, source_id, content, embedding, metadata)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (source_table, source_id)
                          DO UPDATE SET
                            content    = EXCLUDED.content,
                            embedding  = EXCLUDED.embedding,
                            metadata   = EXCLUDED.metadata,
                            created_at = CURRENT_TIMESTAMP;
                        """,
                        (
                            item["source_table"],
                            item["source_id"],
                            item["rewritten_content"],
                            emb_list,
                            meta,  # JSONB
                        ),
                    )
                conn.commit()
                total += len(batch)

        log.info("嵌入并入库完成，共处理 %s 条", total)
        return total

    def _ensure_table(self, conn, vector_dim: int, log: logging.Logger) -> None:
        """
        确保表存在，如果不存在则创建

        表结构：
        - id: 自增主键
        - source_table: 来源表名
        - source_id: 原始记录ID
        - content: 重写后的文本
        - embedding: 向量
        - metadata: JSONB（存储所有原始字段）
        - created_at: 创建时间
        """
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.searchable_documents');")
            table_exists = cur.fetchone()[0] is not None

            if not table_exists:
                log.info("创建新表 searchable_documents（通用版本）...")
                cur.execute(
                    f"""
                    CREATE TABLE searchable_documents (
                        id BIGSERIAL PRIMARY KEY,
                        source_table  TEXT NOT NULL,
                        source_id     TEXT NOT NULL,
                        content       TEXT NOT NULL,
                        embedding     vector({vector_dim}),
                        metadata      JSONB,
                        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(source_table, source_id)
                    );
                    """
                )

                # 创建索引
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_source_pair
                    ON searchable_documents(source_table, source_id);
                    """
                )

                # JSONB GIN 索引（加速 JSON 查询）
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_metadata
                    ON searchable_documents USING GIN (metadata);
                    """
                )

                conn.commit()
                log.info("表创建完成")
                return

            # 表已存在，检查是否需要迁移
            log.info("检测到表已存在，检查结构...")

            # 检查是否有旧的列（company_name等）
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'searchable_documents'
                  AND column_name IN ('company_name', 'report_year', 'credit_no', 'origin_status')
            """
            )
            old_columns = [row[0] for row in cur.fetchall()]

            if old_columns:
                log.warning(f"检测到旧版表结构（包含列: {old_columns}）")
                log.warning("建议运行迁移脚本将数据迁移到新表结构")
                log.warning("或使用 VectorStoreWriter（旧版）来处理数据")

            # 确保 metadata 列存在
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'searchable_documents'
                  AND column_name = 'metadata'
            """
            )

            if not cur.fetchone():
                log.info("添加 metadata 列...")
                cur.execute(
                    "ALTER TABLE searchable_documents ADD COLUMN IF NOT EXISTS metadata JSONB;"
                )

                # 创建 GIN 索引
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_metadata
                    ON searchable_documents USING GIN (metadata);
                """
                )
                conn.commit()
                log.info("metadata 列添加完成")

            # 检查向量维度
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
                log.warning("检测到表向量维度=%s 与 模型维度=%s 不一致", table_dim, vector_dim)

                cur.execute("SELECT COUNT(*) FROM searchable_documents;")
                rowcount = cur.fetchone()[0]

                if rowcount == 0:
                    log.info("表为空，自动调整 embedding 列维度")
                    cur.execute(
                        "ALTER TABLE searchable_documents ALTER COLUMN "
                        f"embedding TYPE vector({vector_dim});"
                    )
                    conn.commit()
                    log.info("维度调整完成")
                else:
                    raise RuntimeError(
                        f"searchable_documents 已有 {rowcount} 条数据且向量维度不一致，"
                        "请先备份数据，清空表或调整向量维度。"
                    )

            conn.commit()

    def _serialize_metadata(self, raw_meta) -> Optional[str]:
        """
        将元数据序列化为 JSON 字符串

        Args:
            raw_meta: 原始元数据（字典、列表等）

        Returns:
            JSON 字符串
        """
        if raw_meta is None:
            return None
        if isinstance(raw_meta, str):
            return raw_meta
        return json.dumps(raw_meta, ensure_ascii=False, default=str)

    def _to_float_list(self, embedding) -> List[float]:
        """
        将 embedding 转换为 float 列表

        Args:
            embedding: numpy array、list 或 tuple

        Returns:
            float 列表
        """
        if hasattr(embedding, "tolist"):
            embedding = embedding.tolist()
        if (
            isinstance(embedding, (list, tuple))
            and embedding
            and isinstance(embedding[0], (list, tuple))
        ):
            # 展平嵌套列表
            embedding = [x for row in embedding for x in row]
        return [float(x) for x in embedding]

    def close(self) -> None:
        if self._owns_embedding_client:
            self.embedding_client.close()
