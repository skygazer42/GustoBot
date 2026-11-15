"""
Milvus向量数据库封装
使用Milvus作为向量存储引擎
"""

import json
from uuid import uuid4

from typing import List, Dict, Any, Optional
from loguru import logger
from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, utility


class VectorStore:
    """Milvus向量数据库管理类"""

    def __init__(
        self,
        collection_name: str = "recipes",
        host: str = "localhost",
        port: int = 19530,
        dimension: int = 1536,
        index_type: str = "IVF_FLAT",
        metric_type: str = "IP",  # Inner Product (cosine similarity)
    ):
        """
        初始化Milvus向量数据库

        Args:
            collection_name: 集合名称
            host: Milvus服务器地址
            port: Milvus服务器端口
            dimension: 向量维度
            index_type: 索引类型 (IVF_FLAT, IVF_SQ8, HNSW等)
            metric_type: 距离度量类型 (IP, L2, COSINE)
        """
        self.collection_name = collection_name
        self.host = host
        self.port = port
        self.dimension = dimension
        self.index_type = index_type
        self.metric_type = metric_type

        self._connection_alias = f"knowledge_{uuid4().hex}"
        self.collection: Collection

        self._initialize()

    def _initialize(self):
        """初始化Milvus连接和集合"""
        try:
            # 连接到Milvus
            connections.connect(alias=self._connection_alias, host=self.host, port=self.port)
            logger.info(f"Connected to Milvus at {self.host}:{self.port}")

            # 检查集合是否存在
            if utility.has_collection(self.collection_name, using=self._connection_alias):
                self.collection = Collection(self.collection_name, using=self._connection_alias)
                logger.info(f"Loaded existing collection: {self.collection_name}")
            else:
                # 创建新集合
                self._create_collection()
                logger.info(f"Created new collection: {self.collection_name}")

            # 加载集合到内存
            self.collection.load()

        except BaseException:
            try:
                connections.disconnect(self._connection_alias)
            except Exception:
                logger.exception("Failed to disconnect Milvus after initialization failed")
            raise

    def _create_collection(self):
        """创建Milvus集合"""
        # 定义字段
        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=256),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dimension),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="recipe_id", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="difficulty", dtype=DataType.VARCHAR, max_length=128),
        ]

        # 创建集合schema
        schema = CollectionSchema(fields=fields, description="Recipe knowledge base collection")

        # 创建集合
        self.collection = Collection(
            name=self.collection_name, schema=schema, using=self._connection_alias
        )

        # 创建索引
        index_params = {
            "index_type": self.index_type,
            "metric_type": self.metric_type,
            "params": {"nlist": 128} if self.index_type == "IVF_FLAT" else {},
        }

        self.collection.create_index(field_name="embedding", index_params=index_params)

        logger.info(f"Created index with type: {self.index_type}")

    def add_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        添加文档到向量数据库

        Args:
            ids: 文档ID列表
            embeddings: 嵌入向量列表
            documents: 文档文本列表
            metadatas: 文档元数据列表

        Returns:
            是否成功
        """
        if metadatas is None:
            metadatas = [{} for _ in ids]
        if not (len(ids) == len(embeddings) == len(documents) == len(metadatas)):
            raise ValueError("Document, metadata and embedding counts must match")

        def _as_varchar(value: Any) -> str:
            if value is None:
                return ""
            return str(value)

        # 准备插入数据
        entities = [
            ids,
            embeddings,
            documents,
            [_as_varchar(meta.get("recipe_id")) for meta in metadatas],
            [_as_varchar(meta.get("name")) for meta in metadatas],
            [_as_varchar(meta.get("category")) for meta in metadatas],
            [_as_varchar(meta.get("difficulty")) for meta in metadatas],
        ]

        # 插入数据
        self.collection.insert(entities)
        self.collection.flush()

        logger.info(f"Added {len(ids)} documents to Milvus")
        return True

    def search(
        self, query_embedding: List[float], top_k: int = 10, filter_expr: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        搜索相似文档

        Args:
            query_embedding: 查询向量
            top_k: 返回结果数量
            filter_expr: 过滤表达式 (例如: "category == '家常菜'")

        Returns:
            搜索结果列表
        """
        # 搜索参数
        search_params = {"metric_type": self.metric_type, "params": {"nprobe": 10}}

        # 执行搜索
        results = self.collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=filter_expr,
            output_fields=["id", "content", "recipe_id", "name", "category", "difficulty"],
        )

        # 格式化结果
        formatted_results = []
        for hits in results:
            for hit in hits:
                formatted_results.append(
                    {
                        "id": hit.entity.get("id"),
                        "content": hit.entity.get("content"),
                        "score": float(hit.score),
                        "metadata": {
                            "recipe_id": hit.entity.get("recipe_id"),
                            "name": hit.entity.get("name"),
                            "category": hit.entity.get("category"),
                            "difficulty": hit.entity.get("difficulty"),
                        },
                    }
                )

        logger.info(f"Found {len(formatted_results)} results")
        return formatted_results

    def delete_documents(self, ids: List[str]) -> bool:
        """
        删除文档

        Args:
            ids: 文档ID列表

        Returns:
            是否成功
        """
        expr = "id in " + json.dumps(ids, ensure_ascii=False)
        self.collection.delete(expr)
        self.collection.flush()

        logger.info(f"Deleted {len(ids)} documents")
        return True

    def get_collection_stats(self) -> Dict[str, Any]:
        """获取集合统计信息"""
        stats = self.collection.num_entities
        return {
            "name": self.collection_name,
            "document_count": stats,
            "dimension": self.dimension,
            "index_type": self.index_type,
            "metric_type": self.metric_type,
        }

    def clear_collection(self) -> bool:
        """清空集合"""
        self.collection.drop()
        self._create_collection()
        self.collection.load()

        logger.info(f"Cleared collection: {self.collection_name}")
        return True

    def close(self):
        """关闭连接"""
        connections.disconnect(self._connection_alias)
        logger.info("Disconnected from Milvus")
