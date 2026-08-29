
import json
import logging
import re
from typing import List, Optional

import psycopg2
from pgvector.psycopg2 import register_vector

from kb_service.clients.embedding import EmbeddingClient
from kb_service.core.config import Config
from kb_service.services.reranker import RerankerClient


class VectorSearcher:
    """Similarity search helper backed by pgvector."""

    def __init__(self, config: Config):
        self.config = config
        self.embedding_client = EmbeddingClient(config)
        self.logger = logging.getLogger(__name__)
        self.rerank_client: RerankerClient | None = None
        if self.config.rerank_enabled:
            try:
                self.rerank_client = RerankerClient(config)
                self.logger.info(
                    "Reranker enabled (provider=%s, max_candidates=%s)",
                    self.config.rerank_provider,
                    self.config.rerank_max_candidates,
                )
            except Exception as exc:  # pragma: no cover
                self.logger.warning("初始化 RerankerClient 失败，将回退到纯向量排序: %s", exc)
                self.rerank_client = None

    def search_similar(
        self,
        query: str,
        top_k: int = 5,
        threshold: Optional[float] = None,
        metric: str = "cosine",
        company_filter: Optional[str] = None,
        source_tables: Optional[List[str]] = None,
    ) -> List[dict]:
        self.logger.info("开始搜索: %s... (metric=%s)", query[:50], metric)

        qvec = self.embedding_client.embed_texts([query])[0]
        qvec = qvec.tolist() if hasattr(qvec, "tolist") else list(qvec)

        if metric == "l2":
            order_expr = "embedding <-> q.v"
            sim_expr = "1.0 / (1.0 + (embedding <-> q.v))"
            dist_expr = "embedding <-> q.v"
        else:
            order_expr = "embedding <=> q.v"
            sim_expr = "1.0 - (embedding <=> q.v)"
            dist_expr = "embedding <-> q.v"

        sql = f"""
        WITH q AS (SELECT %s::vector AS v)
        SELECT
          id, source_table, source_id, metadata, content,
          {sim_expr}  AS similarity,
          {dist_expr} AS distance
        FROM searchable_documents, q
        WHERE embedding IS NOT NULL
        """
        params: List = [qvec]

        if company_filter:
            # 使用 JSONB 查询
            sql += " AND (metadata->>'company_name' ILIKE %s OR metadata->>'企业名称' ILIKE %s)"
            params.append(f"%{company_filter}%")
            params.append(f"%{company_filter}%")

        if source_tables:
            sql += " AND source_table = ANY(%s)"
            params.append(source_tables)

        if threshold is not None:
            sql += f" AND ({sim_expr}) >= %s::float8"
            params.append(float(threshold))

        sql += f" ORDER BY {order_expr} LIMIT %s;"
        params.append(int(top_k))

        rows = []
        conn = psycopg2.connect(**self.config.db_config)
        try:
            register_vector(conn)
            with conn.cursor() as cur:
                try:
                    cur.execute("SET ivfflat.probes = 10;")
                except Exception:  # pragma: no cover - optional extension
                    pass
                self.logger.debug(cur.mogrify(sql, params).decode())
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()

        results = []
        for row in rows:
            # 解析 metadata
            metadata_dict = {}
            if row[3]:  # metadata
                try:
                    metadata_dict = json.loads(row[3]) if isinstance(row[3], str) else row[3]
                except Exception:  # pragma: no cover - best effort
                    pass

            content = row[4]
            if isinstance(content, memoryview):
                content = content.tobytes().decode("utf-8", errors="ignore")
            elif isinstance(content, bytes):
                content = content.decode("utf-8", errors="ignore")

            similarity = float(row[5])

            item = {
                "id": str(row[0]),
                "source_table": row[1],
                "source_id": str(row[2]) if row[2] is not None else None,
                "metadata": metadata_dict,
                "content": content,
                "similarity": similarity,
                "distance": float(row[6]),
                "score": similarity,
                "document_id": str(row[2]) if row[2] is not None else str(row[0]),
                "source": metadata_dict.get("source_file")
                or metadata_dict.get("ingest_source")
                or metadata_dict.get("source")
                or metadata_dict.get("url")
                or metadata_dict.get("id")
                or row[1]
                or (str(row[2]) if row[2] is not None else str(row[0])),
            }
            results.append(item)

        if self.rerank_client and results:
            results = self._apply_reranker(query, results)

        self.logger.info("找到 %s 个相似结果", len(results))
        return results

    def hybrid_search(
        self,
        query: str,
        vector_top_k: int = 20,
        rerank_top_k: int = 10,
        threshold: Optional[float] = None,
        metric: str = "cosine",
        source_tables: Optional[List[str]] = None,
    ) -> dict:
        """
        混合召回：向量检索 + Rerank 精排

        Args:
            query: 查询文本
            vector_top_k: 向量检索返回的候选数
            rerank_top_k: Rerank 后返回的结果数
            threshold: 相似度阈值
            metric: 距离度量方式
            source_tables: 限制检索的表范围

        Returns:
            包含 vector_results, rerank_results, hybrid_results 的字典
        """
        self.logger.info("混合召回: %s... (vector_top_k=%d, rerank_top_k=%d)", query[:50], vector_top_k, rerank_top_k)

        # 1. 向量检索
        vector_results = self.search_similar(
            query=query,
            top_k=vector_top_k,
            threshold=threshold,
            metric=metric,
            source_tables=source_tables,
        )

        # 2. Rerank（如果启用且有结果）
        rerank_results = []
        if self.rerank_client and vector_results:
            # 准备 candidates
            candidates = []
            for item in vector_results[:min(vector_top_k, len(vector_results))]:
                candidates.append({
                    "id": str(item["id"]),
                    "text": item.get("content") or "",
                    "metadata": {
                        "source_table": item.get("source_table"),
                        "source_id": item.get("source_id"),
                        "similarity": item.get("similarity"),
                    },
                })

            # 调用 rerank
            reranked = self.rerank_client.rerank(query, candidates, top_n=rerank_top_k) if candidates else None

            if reranked:
                # 构建 ID 映射
                id_map = {str(item["id"]): item for item in vector_results}

                # 按 rerank 分数排序
                for entry in reranked:
                    item = id_map.get(entry["id"])
                    if item:
                        item_copy = item.copy()
                        item_copy["rerank_score"] = entry["score"]
                        rerank_results.append(item_copy)

                self.logger.info("Rerank 完成: %d 个结果", len(rerank_results))

        # 3. 混合结果：优先返回交集，其次 rerank，最后向量相似度
        hybrid_results = []

        if rerank_results:
            # 找出向量结果和 rerank 结果的交集
            vector_ids = {item["id"] for item in vector_results}
            rerank_ids = {item["id"] for item in rerank_results}
            intersection_ids = vector_ids & rerank_ids

            if intersection_ids:
                # 有交集：返回交集中的结果（按 rerank 顺序）
                hybrid_results = [item for item in rerank_results if item["id"] in intersection_ids]
                self.logger.info("返回交集结果: %d 个（向量 %d + Rerank %d）",
                               len(hybrid_results), len(vector_ids), len(rerank_ids))
            else:
                # 没有交集：只返回 rerank 结果
                hybrid_results = rerank_results
                self.logger.info("向量和 Rerank 无交集，返回 Rerank 结果: %d 个", len(hybrid_results))
        else:
            # 没有 rerank：返回向量检索结果
            hybrid_results = vector_results
            # 添加 rerank_score 字段以保持结构一致
            for item in hybrid_results:
                if "rerank_score" not in item:
                    item["rerank_score"] = None
            self.logger.info("未启用 Rerank，返回向量检索结果: %d 个", len(hybrid_results))

        return {
            "query": query,
            "results": hybrid_results,
            "count": len(hybrid_results),
        }

    def search_and_display(
        self,
        query: str,
        top_k: int = 10,
        threshold: Optional[float] = None,
        metric: str = "cosine",
        company_filter: Optional[str] = None,
        preview_len: int = 240,
    ) -> List[dict]:
        results = self.search_similar(
            query=query,
            top_k=top_k,
            threshold=threshold,
            metric=metric,
            company_filter=company_filter,
        )

        if not results:
            print(f"\n查询: {query}\n没有找到相关结果 (metric={metric}, threshold={threshold})")
            return results

        print(f"\n查询: {query}")
        print(f"metric={metric}, threshold={threshold}, 返回 {len(results)} 条\n" + "=" * 100)

        def preview(txt: str, length: int) -> str:
            if not txt:
                return ""
            stripped = re.sub(r"\s+", " ", str(txt))
            return (stripped[:length] + "…") if len(stripped) > length else stripped

        for idx, row in enumerate(results, start=1):
            rerank_info = f" rerank={row['rerank_score']:.4f}" if row.get("rerank_score") is not None else ""
            print(
                f"\n【结果 {idx}】 sim={row['similarity']:.4f}{rerank_info}  dist={row['distance']:.4f}  "
                f"id={row['id']}  company={row.get('company_name') or '-'}  "
                f"year={row.get('report_year') or '-'}  source={row.get('source_table') or '-'}"
            )
            print("内容预览：", preview(row.get("content", ""), preview_len))
            if row.get("metadata"):
                print("元数据：", preview(row["metadata"], 160))
            print("-" * 100)
        return results

    def _apply_reranker(self, query: str, results: List[dict]) -> List[dict]:
        """
        应用重排序模型对搜索结果进行优化
        支持可选的分数融合策略
        """
        max_candidates = max(1, self.config.rerank_max_candidates or 1)
        candidates = []
        for item in results[:max_candidates]:
            candidates.append(
                {
                    "id": str(item["id"]),
                    "text": item.get("content") or "",
                    "metadata": {
                        "source_table": item.get("source_table"),
                        "source_id": item.get("source_id"),
                        "similarity": item.get("similarity"),
                    },
                }
            )

        reranked = self.rerank_client.rerank(query, candidates) if candidates else None
        if not reranked:
            return results

        # 构建 ID 到结果的映射
        id_map = {str(item["id"]): item for item in results}

        # 如果启用了分数融合
        fusion_alpha = self.config.rerank_score_fusion_alpha
        if fusion_alpha is not None and 0 < fusion_alpha < 1:
            # 收集向量分数和 rerank 分数
            vec_scores = []
            rerank_scores_dict = {entry["id"]: entry["score"] for entry in reranked}

            for item in results[:max_candidates]:
                item_id = str(item["id"])
                if item_id in rerank_scores_dict:
                    vec_scores.append(item.get("similarity", 0.0))

            # Z-score 标准化
            if vec_scores and len(vec_scores) > 1:
                vec_z = self.rerank_client.zscore_normalize(vec_scores)
                rerank_z = self.rerank_client.zscore_normalize(
                    [rerank_scores_dict[str(item["id"])] for item in results[:max_candidates]
                     if str(item["id"]) in rerank_scores_dict]
                )

                # 应用融合分数
                z_idx = 0
                for item in results[:max_candidates]:
                    item_id = str(item["id"])
                    if item_id in rerank_scores_dict:
                        item["rerank_score"] = rerank_scores_dict[item_id]
                        item["final_score"] = (
                            fusion_alpha * vec_z[z_idx] +
                            (1 - fusion_alpha) * rerank_z[z_idx]
                        )
                        z_idx += 1

                # 按融合分数排序
                results_with_final = [
                    item for item in results[:max_candidates]
                    if "final_score" in item
                ]
                results_without_final = [
                    item for item in results[max_candidates:]
                ]
                results_with_final.sort(key=lambda x: x.get("final_score", float("-inf")), reverse=True)

                ordered = results_with_final + results_without_final
                self.logger.info(
                    "Reranker 已对 %s 条候选进行重排序（融合模式 α=%.2f）",
                    len(results_with_final),
                    fusion_alpha
                )
                return ordered

        # 不使用融合，直接按 rerank 分数排序
        ordered: List[dict] = []
        seen: set[str] = set()

        for entry in reranked:
            item = id_map.get(entry["id"])
            if not item:
                continue
            item["rerank_score"] = entry["score"]
            ordered.append(item)
            seen.add(entry["id"])

        # 添加未被 rerank 的结果（保持原顺序）
        for item in results:
            key = str(item["id"])
            if key in seen:
                continue
            item.setdefault("rerank_score", None)
            ordered.append(item)

        self.logger.info("Reranker 已对 %s 条候选进行重排序", len(seen))
        return ordered
