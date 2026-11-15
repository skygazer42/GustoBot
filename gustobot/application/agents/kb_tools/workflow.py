"""Document knowledge workflow for local and external retrieval sources."""

from operator import add
from typing import Any, Dict, List, Literal, Optional

import aiohttp
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langgraph.constants import END, START
from langgraph.graph.state import CompiledStateGraph, StateGraph
from pydantic import BaseModel, Field
from typing_extensions import Annotated, TypedDict

from gustobot.config import settings
from gustobot.infrastructure.core.logger import get_logger
from gustobot.infrastructure.knowledge import KnowledgeService

from ..utils import message_text
from .sources import collect_sources, strip_generated_source_section

kb_logger = get_logger(service="kb-multi-tool")


class KBGuardrailsDecision(BaseModel):
    decision: Literal["proceed", "end"]
    summary: Optional[str] = None
    rationale: Optional[str] = None


class KBRouteDecision(BaseModel):
    route: Literal["local", "external", "hybrid"]
    rationale: str
    tools: List[Literal["milvus", "postgres"]] = Field(
        description="本地知识源检索工具列表，支持 milvus/postgres",
    )


class KBInputState(TypedDict):
    question: str
    history: List[Dict[str, str]]


class KBWorkflowState(TypedDict):
    question: str
    history: List[Dict[str, str]]
    guardrails_decision: str
    summary: str
    route: str
    kb_tools: List[str]
    milvus_results: List[Dict[str, Any]]
    postgres_results: List[Dict[str, Any]]
    local_results: List[Dict[str, Any]]
    external_results: List[Dict[str, Any]]
    answer: str
    steps: Annotated[List[str], add]
    sources: Annotated[List[Dict[str, str]], add]
    search_errors: Annotated[List[str], add]


class KBOutputState(TypedDict):
    answer: str
    steps: List[str]
    sources: List[Dict[str, str]]


def create_kb_multi_tool_workflow(
    llm: BaseChatModel,
    knowledge_service: KnowledgeService,
    *,
    top_k: Optional[int] = None,
    similarity_threshold: Optional[float] = None,
    filter_expr: Optional[str] = None,
    allow_external: Optional[bool] = None,
    external_search_url: Optional[str] = None,
    external_search_timeout: Optional[float] = None,
    scope_description: Optional[str] = None,
) -> CompiledStateGraph:
    """
    Create a multi-tool workflow for knowledge base queries.

    This workflow performs guardrails checking, routes the question to the most
    appropriate retrieval source (local vector store, external API, or both),
    and then synthesises a response with safety-aware instructions.
    """

    effective_top_k = settings.KB_TOP_K if top_k is None else top_k
    if effective_top_k <= 0:
        raise ValueError("top_k must be positive")
    effective_threshold = (
        similarity_threshold
        if similarity_threshold is not None
        else settings.KB_SIMILARITY_THRESHOLD
    )

    allow_external_search = (
        allow_external if allow_external is not None else settings.KB_ENABLE_EXTERNAL_SEARCH
    )

    ingest_service_base = (
        settings.INGEST_SERVICE_URL.rstrip("/") if settings.INGEST_SERVICE_URL else None
    )

    postgres_search_url = (
        f"{ingest_service_base}/api/v1/knowledge/search" if ingest_service_base else None
    )

    external_url = external_search_url or settings.KB_EXTERNAL_SEARCH_URL

    if allow_external_search and not external_url:
        kb_logger.warning(
            "External search enabled but KB_EXTERNAL_SEARCH_URL 未配置，已自动关闭外部检索。"
        )
        allow_external_search = False

    external_is_postgres = bool(
        allow_external_search
        and external_url
        and postgres_search_url
        and external_url.rstrip("/") == postgres_search_url.rstrip("/")
    )

    if not allow_external_search:
        external_url = None

    request_timeout = (
        external_search_timeout
        if external_search_timeout is not None
        else settings.KB_EXTERNAL_SEARCH_TIMEOUT
    )

    scope_text = (
        scope_description
        if scope_description is not None
        else "根据已接入知识库的文档、记录与实体关系回答问题。"
        "检索结果未提供的信息应明确说明，不编造事实。"
    )

    guardrails_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "你是企业知识库的安全审查员。服务范围：\n"
                    "{scope_text}\n\n"
                    "判断用户问题是否位于该范围，并确保不包含违法、隐私或未授权内容。"
                    "若问题不适宜或不在范围内，请返回 decision='end' 并给出中文 summary；"
                    "否则返回 decision='proceed'。"
                ),
            ),
            ("human", "用户问题：{question}"),
        ]
    ).partial(scope_text=scope_text)
    guardrails_chain = guardrails_prompt | llm.with_structured_output(
        KBGuardrailsDecision, method="function_calling"
    )

    router_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "你是知识库检索路由器。根据问题与对话历史选择合适的检索来源。\n\n"
                    "## 服务范围\n{scope_text}\n\n"
                    "## 本地知识源说明\n"
                    "- **postgres**（PostgreSQL pgvector）：**第一优先级**，存放结构化表格数据、Excel导入的枚举字段\n"
                    "  - 数据更准确、查询更快、覆盖面广\n"
                    "  - 适合：实体属性、分类、事件和关系等事实查询\n"
                    "  - 执行策略：系统会**先查 postgres**，如果有结果就直接使用，**不会查询 milvus**\n"
                    "- **milvus**（Milvus向量库）：存放长文本、文章、手册等非结构化内容\n"
                    "  - 同时选择两个来源时，只有 postgres 无结果才会查询 milvus\n\n"
                    "## 路由决策规则（严格执行：postgres 优先）\n"
                    "请根据问题特征选择合适的路由和工具：\n\n"
                    "**1. 通用知识查询（默认推荐）**\n"
                    "   - 适用于：事实、背景、分类、特征和关系等问题\n"
                    "   - route: local, tools: ['postgres', 'milvus']\n"
                    "   - 执行流程：postgres → 有结果则返回 → 无结果才用 milvus 兜底\n\n"
                    "**2. 明确的结构化查询（postgres 足够）**\n"
                    "   - 适用于：名称、属性、事件或实体关系查询\n"
                    "   - route: local, tools: ['postgres']\n\n"
                    "**3. 明确需要长文本叙事（可能需要 milvus）**\n"
                    '   - 适用于：用户明确要求"完整说明"、"详细背景"、"长篇介绍"\n'
                    "   - route: local, tools: ['milvus']\n\n"
                    "**4. 外部检索类（需要外网资料）**\n"
                    "   - 本地知识库可能不足，需要外部检索\n"
                    "   - route: hybrid, tools: ['milvus']\n\n"
                    "## 输出格式\n"
                    "请输出三个字段：\n"
                    "- route：local（本地）/ external（外部）/ hybrid（混合）\n"
                    "- tools：列表，元素为 'postgres' 和/或 'milvus'\n"
                    "  - **默认推荐**: ['postgres', 'milvus'] 让系统自动优先使用 postgres\n"
                    "- rationale：中文简要说明选择理由（1-2句话）"
                ),
            ),
            (
                "human",
                "用户问题：{question}\n\n最近对话历史：\n{history}",
            ),
        ]
    ).partial(scope_text=scope_text)
    router_chain = router_prompt | llm.with_structured_output(
        KBRouteDecision, method="function_calling"
    )

    final_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "你是知识库问答助手，需要依据给定检索结果作答。\n"
                    "服务范围：\n{scope_text}\n\n请遵循：\n"
                    "1. 在服务范围内回答，依据检索材料说明事实，不编造材料中缺失的信息。\n"
                    "2. 若信息不足，说明知识库暂无相关记载，并提示需要补充的资料。\n"
                    "3. 语气专业、友好，回答使用简体中文。\n"
                    "4. 如问题超出服务范围，应说明限制。\n"
                    "5. 区分并融合来自不同数据源的要点，避免重复叙述。\n"
                    "6. 不要在回答正文中生成参考资料、引用来源或数据库名称；"
                    "系统会根据真实检索结果单独展示结构化来源。"
                ),
            ),
            (
                "human",
                (
                    "用户问题：{question}\n\n"
                    "Milvus 向量检索结果：\n{milvus_context}\n\n"
                    "PostgreSQL 结构化检索结果：\n{postgres_context}\n\n"
                    "外部检索结果：\n{external_context}"
                ),
            ),
        ]
    ).partial(scope_text=scope_text)

    def _history_to_text(history: List[Dict[str, str]], limit: int = 4) -> str:
        if not history:
            return "（无历史对话）"
        segments: List[str] = []
        for item in history[-limit:]:
            role = item.get("role", "user")
            content = item.get("content", "")
            segments.append(f"{role}: {content}")
        return "\n".join(segments)

    TOOL_LABELS = {
        "milvus": "Milvus",
        "postgres": "PostgreSQL",
    }

    def _format_results(
        results: List[Dict[str, Any]],
        *,
        default_label: str,
        empty_hint: str,
    ) -> str:
        if not results:
            return empty_hint
        snippets: List[str] = []
        for idx, doc in enumerate(results[:effective_top_k]):
            content = doc["content"]
            snippet = content.strip().replace("\n", " ")
            snippet = snippet[:500]
            meta = doc.get("metadata") or {}
            source = (
                doc.get("source")
                or doc.get("source_table")
                or meta.get("source")
                or meta.get("source_table")
                or meta.get("title")
                or ""
            )
            tool_label = TOOL_LABELS.get(str(doc.get("tool", "")).lower(), default_label)
            tag = f"[{tool_label}#{idx + 1}] {snippet}"
            if source:
                tag = f"{tag}\n来源：{source}"
            snippets.append(tag)
        return "\n\n".join(snippets)

    def _format_external_results(results: List[Dict[str, Any]]) -> str:
        if not results:
            return "（无外部检索结果）"
        snippets: List[str] = []
        for idx, item in enumerate(results[:effective_top_k]):
            content = item["content"]
            snippet = content.strip().replace("\n", " ")
            snippet = snippet[:500]
            meta = item.get("metadata") or {}
            source = (
                item.get("source")
                or item.get("source_table")
                or meta.get("source")
                or meta.get("source_table")
                or meta.get("url")
                or ""
            )
            tag = f"[外部#{idx + 1}] {snippet}"
            if source:
                tag = f"{tag}\n来源：{source}"
            snippets.append(tag)
        return "\n\n".join(snippets)

    async def guardrails(state: KBWorkflowState) -> Dict[str, Any]:
        question = state["question"]
        decision = KBGuardrailsDecision.model_validate(
            await guardrails_chain.ainvoke({"question": question})
        )
        summary = decision.summary or (
            "抱歉，该问题不在当前知识库的支持范围内，请询问与已接入资料相关的问题。"
            if decision.decision == "end"
            else ""
        )
        kb_logger.info("KB guardrails decision: {}", decision.decision)
        return {
            "guardrails_decision": decision.decision,
            "summary": summary,
            "steps": ["guardrails"],
        }

    async def router(state: KBWorkflowState) -> Dict[str, Any]:
        question = state["question"]
        history_text = _history_to_text(state.get("history", []))
        decision = KBRouteDecision.model_validate(
            await router_chain.ainvoke(
                {
                    "question": question,
                    "history": history_text,
                }
            )
        )
        route = decision.route
        if route in {"external", "hybrid"} and not allow_external_search:
            kb_logger.info(
                "Router requested {} but external search is disabled; using local instead.",
                route,
            )
            route = "local"
        tools = decision.tools
        if route != "external" and not tools:
            # 默认使用 postgres + milvus 兜底策略
            tools = ["postgres", "milvus"]
            kb_logger.info("Router 未指定工具，使用默认策略: postgres 优先 + milvus 兜底")
        kb_logger.info(
            "KB router decision: {} tools={} ({})",
            route,
            tools,
            decision.rationale,
        )
        return {
            "route": route,
            "kb_tools": tools,
            "steps": ["router"],
        }

    async def local_search(state: KBWorkflowState) -> Dict[str, Any]:
        """
        优先使用 PostgreSQL pgvector 结构化查询，如果无结果再用 Milvus 兜底。

        执行策略：
        1. 优先查询 PostgreSQL（如果在工具列表中）
        2. 如果 PostgreSQL 有结果（>= 1条），直接使用，跳过 Milvus
        3. 如果 PostgreSQL 无结果或未被选择，查询 Milvus 作为兜底
        """
        question = state["question"]
        if not question.strip():
            return {
                "milvus_results": [],
                "postgres_results": [],
                "local_results": [],
                "steps": ["local_search"],
            }

        selected_tools = state["kb_tools"]

        milvus_results: List[Dict[str, Any]] = []
        postgres_results: List[Dict[str, Any]] = []
        search_errors: List[str] = []

        # Step 1: 优先查询 PostgreSQL（如果在工具列表中）
        should_try_postgres = "postgres" in selected_tools
        should_try_milvus = "milvus" in selected_tools

        # 确保优先级：如果同时选择了两个工具，先尝试 PostgreSQL
        if should_try_postgres:
            if not postgres_search_url:
                kb_logger.warning(
                    "PostgreSQL 工具被选中，但 INGEST_SERVICE_URL 未配置，跳过 PostgreSQL 直接使用 Milvus。"
                )
                # 如果 PostgreSQL 不可用，直接使用 Milvus
                should_try_milvus = True
            else:
                kb_logger.info("优先查询 PostgreSQL pgvector 结构化数据库")
                payload: Dict[str, Any] = {
                    "query": question,
                    "top_k": effective_top_k,
                }
                if settings.KB_POSTGRES_SIMILARITY_THRESHOLD is not None:
                    payload["threshold"] = settings.KB_POSTGRES_SIMILARITY_THRESHOLD
                try:
                    timeout_cfg = aiohttp.ClientTimeout(total=request_timeout)
                    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
                        async with session.post(postgres_search_url, json=payload) as response:
                            if response.status != 200:
                                error_text = await response.text()
                                raise RuntimeError(
                                    f"PostgreSQL search failed ({response.status}): {error_text}"
                                )
                            body = await response.json()
                            data_results = body["results"]
                            if not isinstance(data_results, list):
                                raise TypeError("PostgreSQL search results must be a list")
                            for idx, item in enumerate(data_results):
                                item_copy = dict(item)
                                metadata_copy = dict(item_copy.get("metadata") or {})
                                item_copy["metadata"] = metadata_copy
                                item_copy["tool"] = "postgres"
                                item_copy["similarity"] = float(item_copy["similarity"])
                                for identifier in (
                                    item_copy.get("id"),
                                    item_copy.get("document_id"),
                                    item_copy.get("source_id"),
                                ):
                                    if identifier is not None and identifier != "":
                                        item_copy["id"] = str(identifier)
                                        break
                                else:
                                    item_copy["id"] = f"postgres_{idx}"
                                postgres_results.append(item_copy)
                            if postgres_results and knowledge_service.reranker.enabled:
                                postgres_results = await knowledge_service.reranker.rerank(
                                    question, postgres_results, effective_top_k
                                )
                            filtered_postgres: List[Dict[str, Any]] = []
                            for doc in postgres_results:
                                if doc["similarity"] < settings.KB_POSTGRES_SIMILARITY_THRESHOLD:
                                    continue
                                # A reranker may return the original vector results
                                # when ranking is unavailable; no score was measured.
                                rerank_score = doc.get("rerank_score")
                                if (
                                    knowledge_service.reranker.enabled
                                    and rerank_score is not None
                                    and float(rerank_score) < settings.KB_POSTGRES_RERANK_THRESHOLD
                                ):
                                    continue
                                filtered_postgres.append(doc)
                            postgres_results = filtered_postgres[:effective_top_k]
                            kb_logger.info(
                                "PostgreSQL 返回 {} 条结果，过滤后保留 {} 条",
                                len(data_results),
                                len(postgres_results),
                            )
                except Exception as exc:  # pragma: no cover - defensive logging
                    kb_logger.exception("PostgreSQL knowledge search error: {}", exc)
                    postgres_results = []
                    search_errors.append(f"PostgreSQL: {exc}")

        # Step 2: 根据 PostgreSQL 结果决定是否需要 Milvus 兜底
        if postgres_results:
            # PostgreSQL 有结果，直接使用，跳过 Milvus
            kb_logger.info(
                "PostgreSQL 有结果（{}条），直接使用结构化数据，跳过 Milvus 向量查询",
                len(postgres_results),
            )
            combined_results = postgres_results
        else:
            # PostgreSQL 无结果或不可用，使用 Milvus 兜底
            if should_try_milvus:
                kb_logger.info("PostgreSQL 无结果，使用 Milvus 向量库兜底")

                try:
                    docs = await knowledge_service.search(
                        query=question,
                        top_k=effective_top_k,
                        similarity_threshold=effective_threshold,
                        filter_expr=filter_expr,
                        filter_by_similarity=not knowledge_service.reranker.enabled,
                    )
                    for doc in docs:
                        doc_copy = dict(doc)
                        metadata_copy = dict(doc.get("metadata") or {})
                        doc_copy["metadata"] = metadata_copy
                        doc_copy["tool"] = "milvus"
                        milvus_results.append(doc_copy)
                    kb_logger.info("Milvus 兜底返回 {} 条结果", len(milvus_results))
                except Exception as exc:  # pragma: no cover - defensive logging
                    kb_logger.exception("Milvus knowledge search failed: {}", exc)
                    milvus_results = []
                    search_errors.append(f"Milvus: {exc}")
                combined_results = milvus_results
            else:
                kb_logger.warning("未选择任何可用的知识库工具")
                combined_results = []

        route = state["route"]
        if (
            not combined_results
            and route in {"local", "hybrid"}
            and allow_external_search
            and external_url
        ):
            kb_logger.info("Local searches empty, falling back to external search.")
            route = "external"

        return {
            "milvus_results": milvus_results,
            "postgres_results": postgres_results,
            "local_results": combined_results,
            "route": route,
            "search_errors": search_errors,
            "steps": ["local_search"],
        }

    async def external_search(state: KBWorkflowState) -> Dict[str, Any]:
        if not (allow_external_search and external_url):
            return {"external_results": [], "steps": ["external_search"]}

        if external_is_postgres and "postgres" in state["kb_tools"]:
            kb_logger.debug(
                "Skip external search: router already执行了 PostgreSQL 工具，且外部检索与其同源。"
            )
            return {"external_results": [], "steps": ["external_search"]}

        question = state["question"]
        if not question.strip():
            return {"external_results": [], "steps": ["external_search"]}

        payload: Dict[str, Any] = {
            "query": question,
            "top_k": effective_top_k,
        }
        if effective_threshold is not None:
            payload["threshold"] = effective_threshold

        results: List[Dict[str, Any]] = []
        search_errors: List[str] = []
        try:
            timeout_cfg = aiohttp.ClientTimeout(total=request_timeout)
            async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
                async with session.post(external_url, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(
                            f"External search failed ({response.status}): {error_text}"
                        )
                    body = await response.json()
                    results = body["results"]
                    if not isinstance(results, list):
                        raise TypeError("External search results must be a list")
        except Exception as exc:  # pragma: no cover - defensive logging
            kb_logger.exception("External KB search error: {}", exc)
            results = []
            search_errors.append(f"External: {exc}")

        return {
            "external_results": results,
            "search_errors": search_errors,
            "steps": ["external_search"],
        }

    async def finalize(state: KBWorkflowState) -> KBOutputState:
        if state["guardrails_decision"] == "end":
            summary = state.get("summary") or "抱歉，该问题暂时无法回答。"
            return {"answer": summary, "sources": [], "steps": ["finalize"]}

        milvus_results = state.get("milvus_results", [])
        postgres_results = state.get("postgres_results", [])
        local_results = state.get("local_results", []) or (milvus_results + postgres_results)
        external_results = state.get("external_results", [])

        milvus_context = _format_results(
            milvus_results, default_label="Milvus", empty_hint="（Milvus 暂无检索结果）"
        )
        postgres_context = _format_results(
            postgres_results, default_label="PostgreSQL", empty_hint="（PostgreSQL 暂无检索结果）"
        )
        local_context = _format_results(
            local_results, default_label="本地", empty_hint="（无本地检索结果）"
        )
        external_context = _format_external_results(external_results)

        sources = collect_sources(
            [
                ("milvus", milvus_results),
                ("postgres", postgres_results),
                ("external", external_results),
            ]
        )

        if not local_results and not external_results:
            if state.get("search_errors"):
                raise RuntimeError(
                    "Knowledge retrieval failed: " + "; ".join(state["search_errors"])
                )
            fallback = "抱歉，当前知识库暂未找到相关记载，请尝试描述得更具体一些或补充相关资料。"
            return {"answer": fallback, "sources": sources, "steps": ["finalize"]}

        messages = final_prompt.format_messages(
            question=state["question"],
            milvus_context=milvus_context,
            postgres_context=postgres_context,
            external_context=external_context,
        )
        try:
            response = await llm.ainvoke(messages)
            answer = message_text(response).strip()
        except Exception as exc:  # pragma: no cover - defensive logging
            kb_logger.exception("Failed to synthesise KB answer: {}", exc)
            answer = (
                local_context if local_context and local_context != "（无本地检索结果）" else ""
            )

        answer = strip_generated_source_section(answer)
        if not answer:
            answer = "检索已完成，但当前无法生成可靠的回答。"

        return {
            "answer": answer,
            "sources": sources,
            "steps": ["finalize"],
        }

    def guardrails_router(state: KBWorkflowState) -> str:
        return "finalize" if state["guardrails_decision"] == "end" else "kb_router"

    def router_edge(state: KBWorkflowState) -> str:
        return "external_search" if state["route"] == "external" else "local_search"

    def local_edge(state: KBWorkflowState) -> str:
        route = state["route"]
        if route in {"hybrid", "external"} and allow_external_search and external_url:
            return "external_search"
        return "finalize"

    graph_builder = StateGraph(
        KBWorkflowState,
        input_schema=KBInputState,
        output_schema=KBOutputState,
    )

    graph_builder.add_node("guardrails", guardrails)
    graph_builder.add_node("kb_router", router)
    graph_builder.add_node("local_search", local_search)
    graph_builder.add_node("external_search", external_search)
    graph_builder.add_node("finalize", finalize)

    graph_builder.add_edge(START, "guardrails")
    graph_builder.add_conditional_edges("guardrails", guardrails_router)
    graph_builder.add_conditional_edges("kb_router", router_edge)
    graph_builder.add_conditional_edges("local_search", local_edge)
    graph_builder.add_edge("external_search", "finalize")
    graph_builder.add_edge("finalize", END)

    return graph_builder.compile()
