from typing import Any, Dict, List, Optional, Literal

from operator import add

import aiohttp

try:  # pragma: no cover - prefer typing_extensions for Pydantic compatibility
    from typing_extensions import Annotated, TypedDict  # type: ignore
except ImportError:  # pragma: no cover - minimal stdlib fallback
    from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_neo4j import Neo4jGraph
from langgraph.constants import END, START
from langgraph.graph.state import CompiledStateGraph, StateGraph
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

# 导入输入输出状态定义
from gustobot.application.agents.kg_sub_graph.agentic_rag_agents.components.state import (
    InputState,
    OutputState,
    OverallState,
)
# 导入guardrails逻辑
from gustobot.application.agents.kg_sub_graph.agentic_rag_agents.components.guardrails.node import create_guardrails_node
# 导入分解节点
from gustobot.application.agents.kg_sub_graph.agentic_rag_agents.components.planner import create_planner_node
# 导入工具选择节点
from gustobot.application.agents.kg_sub_graph.agentic_rag_agents.components.tool_selection import create_tool_selection_node
# 导入 text2cypher 节点
from gustobot.application.agents.kg_sub_graph.agentic_rag_agents.components.cypher_tools import create_cypher_query_node
# 导入Cypher示例检索器基类
from gustobot.application.agents.kg_sub_graph.agentic_rag_agents.retrievers.cypher_examples.base import BaseCypherExampleRetriever
# 导入预定义Cypher节点
from gustobot.application.agents.kg_sub_graph.agentic_rag_agents.components.predefined_cypher import create_predefined_cypher_node
# 导入自定义工具函数节点
from gustobot.application.agents.kg_sub_graph.agentic_rag_agents.components.customer_tools import create_graphrag_query_node
from gustobot.application.agents.kg_sub_graph.agentic_rag_agents.components.text2cypher.text2sql_tool import create_text2sql_tool_node

from gustobot.config import settings
from gustobot.application.agents.kb_tools.sources import (
    collect_sources,
    strip_generated_source_section,
)
from gustobot.infrastructure.core.logger import get_logger
from gustobot.infrastructure.knowledge import KnowledgeService


from ...components.errors import create_error_tool_selection_node
from ...components.final_answer import create_final_answer_node



from ...components.summarize import create_summarization_node



from .edges import (
    guardrails_conditional_edge,
    map_reduce_planner_to_tool_selection,
)

from dataclasses import dataclass, field
# 强制要求数据类中的所有字段必须以关键字参数的形式提供。即不能以位置参数的方式传递。
@dataclass(kw_only=True)
class AgentState(InputState):
    """The router's classification of the user's query."""
    steps: list[str] = field(default_factory=list)
    """Populated by the retriever. This is a list of documents that the agent can reference."""
    question: str = field(default_factory=str) # 这个参数用来与子图进行交互
    answer: str = field(default_factory=str)  # 这个参数用来与子图进行交互


def create_multi_tool_workflow(
    llm: BaseChatModel,
    graph: Neo4jGraph,
    tool_schemas: List[type[BaseModel]],
    predefined_cypher_dict: Dict[str, str],
    cypher_example_retriever: BaseCypherExampleRetriever,
    scope_description: Optional[str] = None,
    llm_cypher_validation: bool = True,
    max_attempts: int = 3,
    attempt_cypher_execution_on_final_attempt: bool = False,
    default_to_text2cypher: bool = True,
) -> CompiledStateGraph:
    """
    Create a multi tool Agent workflow using LangGraph.
    This workflow allows an agent to select from various tools to complete each identified task.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM to use for processing
    graph : Neo4jGraph
        The Neo4j graph wrapper.
    tool_schemas : List[BaseModel]
        A list of Pydantic class defining the available tools.
    predefined_cypher_dict : Dict[str, str]
        A Python dictionary of Cypher query names as keys and Cypher queries as values.
    scope_description: Optional[str], optional
        A short description of the application scope, by default None
    cypher_example_retriever: BaseCypherExampleRetriever
        The retriever used to collect Cypher examples for few shot prompting.
    llm_cypher_validation : bool, optional
        Whether to perform LLM validation with the provided LLM, by default True
    max_attempts: int, optional
        The max number of allowed attempts to generate valid Cypher, by default 3
    attempt_cypher_execution_on_final_attempt, bool, optional
        THIS MAY BE DANGEROUS.
        Whether to attempt Cypher execution on the last attempt, regardless of if the Cypher contains errors, by default False
    default_to_text2cypher : bool, optional
        Whether to attempt Text2Cypher if no tool calls are returned by the LLM, by default True
    initial_state: Optional[InputState], optional
        An initial state passed from parent graph, by default None

    Returns
    -------
    CompiledStateGraph
        The workflow.
    """
    # 1. 创建guardrails节点
    # Guardrails 节点决定传入的问题是否在检索的范围内（比如是否和电商（自家的产品相关））。如果不在，则提供默认消息，并且工作流路由到最终的答案生成。
    guardrails = create_guardrails_node(
        llm=llm, graph=graph, scope_description=scope_description
    )

    # 2. 如果通过guardrails，则会针对用户的问题进行任务分解
    planner = create_planner_node(llm=llm)

    # 3. 创建cypher_query节点，用来根据用户的问题生成Cypher查询语句 大模型生成Cypher查询语句
    cypher_query = create_cypher_query_node()

    predefined_cypher = create_predefined_cypher_node(
        graph=graph, predefined_cypher_dict=predefined_cypher_dict
    ) #预定义的自定Cypher查询语句

    customer_tools = create_graphrag_query_node() # lightrag_query
    text2sql_query = create_text2sql_tool_node(graph)

    # 工具选择节点，根据用户的问题选择合适的工具
    tool_selection = create_tool_selection_node(
        llm=llm,
        tool_schemas=tool_schemas,
        default_to_text2cypher=default_to_text2cypher,
    )
    summarize = create_summarization_node(llm=llm)

    final_answer = create_final_answer_node()

    # 创建状态图运行时会维护一个“全局状态”（OverallState），入口状态类型是 InputState，最终产出是 OutputState。节点函数读写的就是这个状态。
    main_graph_builder = StateGraph(OverallState, input=InputState, output=OutputState)

    main_graph_builder.add_node(guardrails)# 安全护栏敏感内容过滤、权限/配额校验
    main_graph_builder.add_node(planner) #决定下一步要用的工具/路径。
    main_graph_builder.add_node("cypher_query", cypher_query)#命名 "cypher_query" 的节点，执行 cypher_query 函数（通常是对图数据库生成/执行 Cypher）。
    main_graph_builder.add_node(predefined_cypher) #预设查询（当无需动态生成时）。
    main_graph_builder.add_node("customer_tools", customer_tools) #lightrag_query
    main_graph_builder.add_node("text2sql_query", text2sql_query)
    main_graph_builder.add_node(summarize) # 总结
    main_graph_builder.add_node(tool_selection) #工具选择的中间控制节点（通常结合 planner 的输出）。
    main_graph_builder.add_node(final_answer)


    # 添加边
    main_graph_builder.add_edge(START, "guardrails")
    main_graph_builder.add_conditional_edges(
        "guardrails",
        guardrails_conditional_edge,
    ) #这是条件边：执行完 guardrails 后，不是固定跳到某个节点，而是调用 guardrails_conditional_edge(state) 来返回下一跳的节点名（或一个映射）。
    main_graph_builder.add_conditional_edges(
        "planner",
        map_reduce_planner_to_tool_selection, #据 planner 写进 state 的结果，返回下一个要去的节点名
        ["tool_selection"], #从 planner 出来只能跳到 "tool_selection"，且由 map_reduce_planner_to_tool_selection(state) 来决定（但这里其实被限制成只能选这一个）。
    )

    main_graph_builder.add_edge("cypher_query", "summarize")
    main_graph_builder.add_edge("predefined_cypher", "summarize")
    main_graph_builder.add_edge("customer_tools", "summarize")
    main_graph_builder.add_edge("text2sql_query", "summarize")
    main_graph_builder.add_edge("summarize", "final_answer")

    main_graph_builder.add_edge("final_answer", END)

    return main_graph_builder.compile()


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


class KBOutputState(TypedDict):
    answer: str
    steps: List[str]
    sources: List[Dict[str, str]]


def create_kb_multi_tool_workflow(
    llm: BaseChatModel,
    knowledge_service: Optional[KnowledgeService] = None,
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

    knowledge_service = knowledge_service or KnowledgeService()
    effective_top_k = top_k or settings.KB_TOP_K
    effective_threshold = (
        similarity_threshold
        if similarity_threshold is not None
        else settings.KB_SIMILARITY_THRESHOLD
    )

    allow_external_search = (
        allow_external
        if allow_external is not None
        else settings.KB_ENABLE_EXTERNAL_SEARCH
    )

    ingest_service_base = settings.INGEST_SERVICE_URL.rstrip("/") if settings.INGEST_SERVICE_URL else None

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

    scope_text = scope_description or (
        "菜谱文化知识库仅处理菜谱的历史渊源、命名来历、地域流派、典故故事，以及历史名人与菜谱之间的关联信息。"
        "不包含实际烹饪步骤或食材搭配建议。"
        "禁止回答与烹饪做法、医疗养生、隐私、政治、成人内容或其他未授权主题相关的问题。"
    )

    guardrails_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "你是企业知识库的安全审查员。服务范围：\n"
                    f"{scope_text}\n\n"
                    "判断用户问题是否位于该范围，并确保不包含违法、隐私或未授权内容。"
                    "若问题不适宜或不在范围内，请返回 decision='end' 并给出中文 summary；"
                    "否则返回 decision='proceed'。"
                ),
            ),
            ("human", "用户问题：{question}"),
        ]
    )
    guardrails_chain = guardrails_prompt | llm.with_structured_output(KBGuardrailsDecision)

    router_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "你是菜谱文化知识检索路由器。专门负责将历史文化类问题路由到最合适的知识库。\n\n"
                    "## 服务范围\n"
                    '仅限于"菜谱历史/渊源/命名"、"历史名人与菜谱关系"、"菜谱条目级小传与典故"、"菜系流派介绍"。\n\n'
                    "## 本地知识源说明\n"
                    "- **postgres**（PostgreSQL pgvector）：**第一优先级**，存放结构化表格数据、Excel导入的枚举字段\n"
                    "  - 数据更准确、查询更快、覆盖面广\n"
                    "  - 适合：菜谱名称、菜系、历史事件、人物关系等结构化查询\n"
                    "  - 典型问题：菜谱相关的任何历史文化问题\n"
                    "  - 执行策略：系统会**先查 postgres**，如果有结果就直接使用，**不会查询 milvus**\n"
                    "- **milvus**（Milvus向量库）：**仅作为兜底**，存放长文本、文章、典故故事等非结构化内容\n"
                    "  - 只有在 postgres 无结果时才会查询\n"
                    "  - 典型问题：\"宫保鸡丁的完整历史故事\"、\"川菜的详细发展史\"（需要长篇叙事时）\n\n"
                    "## 路由决策规则（严格执行：postgres 优先）\n"
                    "请根据问题特征选择合适的路由和工具：\n\n"
                    "**1. 通用历史文化查询（默认推荐）**\n"
                    "   - 适用于：大部分历史、典故、由来、文化、背景、流派、特点等问题\n"
                    "   - route: local, tools: ['postgres', 'milvus']\n"
                    "   - 执行流程：postgres → 有结果则返回 → 无结果才用 milvus 兜底\n\n"
                    "**2. 明确的结构化查询（postgres 足够）**\n"
                    "   - 适用于：菜名查询、简短事实查询、人物关系、年代查询\n"
                    "   - route: local, tools: ['postgres']\n\n"
                    "**3. 明确需要长文本叙事（可能需要 milvus）**\n"
                    "   - 适用于：用户明确要求\"完整故事\"、\"详细历史\"、\"长篇介绍\"\n"
                    "   - route: local, tools: ['milvus']\n\n"
                    "**4. 外部检索类（需要外网资料）**\n"
                    "   - 本地知识库可能不足，需要外部检索\n"
                    "   - route: hybrid, tools: ['milvus']\n\n"
                    "**5. 超出范围类（拒绝回答）**\n"
                    "   - 问题涉及烹饪步骤、食材搭配等非文化内容\n"
                    "   - route: local, tools: []（空列表表示无法处理）\n\n"
                    "## 输出格式\n"
                    "请输出三个字段：\n"
                    "- route：local（本地）/ external（外部）/ hybrid（混合）\n"
                    "- tools：列表，元素为 'postgres' 和/或 'milvus'，若拒绝回答则为空列表 []\n"
                    "  - **默认推荐**: ['postgres', 'milvus'] 让系统自动优先使用 postgres\n"
                    "- rationale：中文简要说明选择理由（1-2句话）"
                ),
            ),
            (
                "human",
                "用户问题：{question}\n\n最近对话历史：\n{history}",
            ),
        ]
    )
    router_chain = router_prompt | llm.with_structured_output(KBRouteDecision)

    final_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "你是菜谱文化讲解助手，需要依据给定检索结果作答。请遵循：\n"
                    "1. 仅讨论菜谱的历史背景、命名来历、地域流派、典故或与名人的关联，不要给出烹饪步骤或食用建议。\n"
                    "2. 若信息不足，说明知识库暂无相关记载，并建议向其他模块查询。\n"
                    "3. 语气专业、友好，回答使用简体中文。\n"
                    "4. 如问题超出菜谱文化范围，应委婉拒答并说明理由。\n"
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
    )

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
            content = doc.get("content") or doc.get("document") or ""
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

    def _format_milvus_results(results: List[Dict[str, Any]]) -> str:
        return _format_results(
            results,
            default_label="Milvus",
            empty_hint="（Milvus 暂无检索结果）",
        )

    def _format_postgres_results(results: List[Dict[str, Any]]) -> str:
        return _format_results(
            results,
            default_label="PostgreSQL",
            empty_hint="（PostgreSQL 暂无检索结果）",
        )

    def _format_combined_local_results(results: List[Dict[str, Any]]) -> str:
        return _format_results(
            results,
            default_label="本地",
            empty_hint="（无本地检索结果）",
        )

    def _format_external_results(results: List[Dict[str, Any]]) -> str:
        if not results:
            return "（无外部检索结果）"
        snippets: List[str] = []
        for idx, item in enumerate(results[:effective_top_k]):
            content = item.get("content") or item.get("summary") or ""
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
        question = state.get("question", "")
        decision = await guardrails_chain.ainvoke({"question": question})
        summary = decision.summary or (
            "抱歉，该问题不在菜谱文化知识库的支持范围内，请询问菜谱历史、典故或名人故事相关内容。"
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
        question = state.get("question", "")
        history_text = _history_to_text(state.get("history", []))
        decision = await router_chain.ainvoke(
            {
                "question": question,
                "history": history_text,
            }
        )
        route = decision.route
        if route in {"external", "hybrid"} and not allow_external_search:
            kb_logger.info(
                "Router requested {} but external search is disabled; using local instead.",
                route,
            )
            route = "local"
        tools = [tool for tool in decision.tools or [] if tool in {"milvus", "postgres"}]
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
        question = state.get("question", "")
        if not question.strip():
            return {
                "milvus_results": [],
                "postgres_results": [],
                "local_results": [],
                "steps": ["local_search"],
            }

        selected_tools = state.get("kb_tools") or ["postgres", "milvus"]

        milvus_results: List[Dict[str, Any]] = []
        postgres_results: List[Dict[str, Any]] = []

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
                kb_logger.info("🔍 [优先] 查询 PostgreSQL pgvector 结构化数据库...")
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
                            if response.status == 200:
                                body = await response.json()
                                data_results = body.get("results") or []
                                if isinstance(data_results, list):
                                    for idx, item in enumerate(data_results):
                                        item_copy = dict(item)
                                        metadata_copy = dict(item_copy.get("metadata") or {})
                                        item_copy["metadata"] = metadata_copy
                                        item_copy["tool"] = "postgres"
                                        similarity = (
                                            item_copy.get("similarity")
                                            if item_copy.get("similarity") is not None
                                            else item_copy.get("score")
                                        )
                                        if similarity is not None:
                                            try:
                                                item_copy["similarity"] = float(similarity)
                                            except (TypeError, ValueError):
                                                item_copy["similarity"] = 0.0
                                        item_copy["id"] = str(
                                            item_copy.get("id")
                                            or item_copy.get("document_id")
                                            or item_copy.get("source_id")
                                            or f"postgres_{idx}"
                                        )
                                        postgres_results.append(item_copy)
                                    if postgres_results and knowledge_service.reranker.enabled:
                                        postgres_results = await knowledge_service.reranker.rerank(
                                            question, postgres_results, effective_top_k
                                        )
                                    filtered_postgres: List[Dict[str, Any]] = []
                                    for doc in postgres_results:
                                        similarity = float(doc.get("similarity") or doc.get("score") or 0.0)
                                        rerank_score = float(doc.get("rerank_score") or 0.0)
                                        if knowledge_service.reranker.enabled:
                                            if (
                                                similarity >= settings.KB_POSTGRES_SIMILARITY_THRESHOLD
                                                and rerank_score >= settings.KB_POSTGRES_RERANK_THRESHOLD
                                            ):
                                                filtered_postgres.append(doc)
                                        else:
                                            if similarity >= settings.KB_POSTGRES_SIMILARITY_THRESHOLD:
                                                filtered_postgres.append(doc)
                                    postgres_results = filtered_postgres[:effective_top_k]
                                    kb_logger.info(
                                        "✅ PostgreSQL 返回 {} 条结果，过滤后保留 {} 条",
                                        len(data_results),
                                        len(postgres_results),
                                    )
                                else:
                                    kb_logger.warning(
                                        "Unexpected PostgreSQL search payload structure: {}",
                                        body,
                                    )
                            else:
                                error_text = await response.text()
                                kb_logger.warning(
                                    "PostgreSQL KB search failed ({}): {}",
                                    response.status,
                                    error_text,
                                )
                except Exception as exc:  # pragma: no cover - defensive logging
                    kb_logger.error("PostgreSQL knowledge search error: {}", exc)

        # Step 2: 根据 PostgreSQL 结果决定是否需要 Milvus 兜底
        if postgres_results and len(postgres_results) > 0:
            # PostgreSQL 有结果，直接使用，跳过 Milvus
            kb_logger.info(
                "✅ PostgreSQL 有结果（{}条），直接使用结构化数据，跳过 Milvus 向量查询",
                len(postgres_results)
            )
            combined_results = postgres_results
        else:
            # PostgreSQL 无结果或不可用，使用 Milvus 兜底
            if should_try_milvus:
                if not postgres_results:
                    kb_logger.info("⚠️ PostgreSQL 无结果，使用 Milvus 向量库兜底...")
                else:
                    kb_logger.info("⚠️ PostgreSQL 不可用，使用 Milvus 向量库...")

                try:
                    docs = await knowledge_service.search(
                        query=question,
                        top_k=effective_top_k,
                        similarity_threshold=settings.KB_SIMILARITY_THRESHOLD,
                        filter_expr=filter_expr,
                        filter_by_similarity=not knowledge_service.reranker.enabled,
                    )
                    for doc in docs:
                        doc_copy = dict(doc)
                        metadata_copy = dict(doc.get("metadata") or {})
                        doc_copy["metadata"] = metadata_copy
                        doc_copy["tool"] = "milvus"
                        milvus_results.append(doc_copy)
                    kb_logger.info("✅ Milvus 兜底返回 {} 条结果", len(milvus_results))
                except Exception as exc:  # pragma: no cover - defensive logging
                    kb_logger.error("Milvus knowledge search failed: {}", exc)
                combined_results = milvus_results
            else:
                kb_logger.warning("⚠️ 未选择任何可用的知识库工具")
                combined_results = []

        route = state.get("route", "local")
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
            "steps": ["local_search"],
        }

    async def external_search(state: KBWorkflowState) -> Dict[str, Any]:
        if not (allow_external_search and external_url):
            return {"external_results": [], "steps": ["external_search"]}

        if external_is_postgres and "postgres" in (state.get("kb_tools") or []):
            kb_logger.debug(
                "Skip external search: router already执行了 PostgreSQL 工具，且外部检索与其同源。"
            )
            return {"external_results": [], "steps": ["external_search"]}

        question = state.get("question", "")
        if not question.strip():
            return {"external_results": [], "steps": ["external_search"]}

        payload: Dict[str, Any] = {
            "query": question,
            "top_k": effective_top_k,
        }
        if effective_threshold is not None:
            payload["threshold"] = effective_threshold

        results: List[Dict[str, Any]] = []
        try:
            timeout_cfg = aiohttp.ClientTimeout(total=request_timeout)
            async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
                async with session.post(external_url, json=payload) as response:
                    if response.status == 200:
                        body = await response.json()
                        data_results = body.get("results") or []
                        if isinstance(data_results, list):
                            results = data_results
                        else:
                            kb_logger.warning(
                                "Unexpected external search payload structure: {}",
                                body,
                            )
                    else:
                        error_text = await response.text()
                        kb_logger.warning(
                            "External KB search failed ({}): {}",
                            response.status,
                            error_text,
                        )
        except Exception as exc:  # pragma: no cover - defensive logging
            kb_logger.error("External KB search error: {}", exc)

        return {
            "external_results": results,
            "steps": ["external_search"],
        }

    async def finalize(state: KBWorkflowState) -> KBOutputState:
        if state.get("guardrails_decision") == "end":
            summary = state.get("summary") or "抱歉，该问题暂时无法回答。"
            return {"answer": summary, "sources": [], "steps": ["finalize"]}

        milvus_results = state.get("milvus_results", [])
        postgres_results = state.get("postgres_results", [])
        local_results = state.get("local_results", []) or (milvus_results + postgres_results)
        external_results = state.get("external_results", [])

        milvus_context = _format_milvus_results(milvus_results)
        postgres_context = _format_postgres_results(postgres_results)
        local_context = _format_combined_local_results(local_results)
        external_context = _format_external_results(external_results)

        sources = collect_sources(
            [
                ("milvus", milvus_results),
                ("postgres", postgres_results),
                ("external", external_results),
            ]
        )

        if not local_results and not external_results:
            fallback = "抱歉，菜谱文化知识库暂未找到相关记载，请尝试描述得更具体一些或稍后再试。"
            return {"answer": fallback, "sources": sources, "steps": ["finalize"]}

        messages = final_prompt.format_messages(
            question=state.get("question", ""),
            milvus_context=milvus_context,
            postgres_context=postgres_context,
            external_context=external_context,
        )
        try:
            response = await llm.ainvoke(messages)
            content = getattr(response, "content", None)
            if isinstance(content, str):
                answer = content.strip()
            else:
                answer = str(response)
        except Exception as exc:  # pragma: no cover - defensive logging
            kb_logger.error("Failed to synthesise KB answer: {}", exc)
            answer = local_context if local_context and local_context != "（无本地检索结果）" else ""
            if not answer:
                answer = "检索已完成，但当前无法生成可靠的菜谱文化回答。"

        if not answer:
            answer = "检索已完成，但当前无法生成可靠的菜谱文化回答。"

        answer = strip_generated_source_section(answer)
        if not answer:
            answer = "检索已完成，但当前无法生成可靠的菜谱文化回答。"

        return {
            "answer": answer,
            "sources": sources,
            "steps": ["finalize"],
        }

    def guardrails_router(state: KBWorkflowState) -> str:
        return "finalize" if state.get("guardrails_decision") == "end" else "kb_router"

    def router_edge(state: KBWorkflowState) -> str:
        return "external_search" if state.get("route") == "external" else "local_search"

    def local_edge(state: KBWorkflowState) -> str:
        route = state.get("route", "local")
        if route in {"hybrid", "external"} and allow_external_search and external_url:
            return "external_search"
        return "finalize"

    graph_builder = StateGraph(
        KBWorkflowState,
        input=KBInputState,
        output=KBOutputState,
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
