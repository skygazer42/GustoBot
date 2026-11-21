"""A single knowledge workflow; ontology understanding owns retrieval planning."""

from typing import TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from gustobot.application.messages import message_text
from gustobot.application.services.knowledge_runtime import get_query_service


class InputState(TypedDict):
    """Required input fields accepted by the knowledge agent graph."""

    messages: list[BaseMessage]


class AgentState(InputState, total=False):
    """Intermediate and optional values carried between graph nodes."""

    response: dict


async def answer_knowledge(state: AgentState, *, config: RunnableConfig):
    """Run the knowledge query and adapt its result to the agent state contract."""
    messages = state["messages"]
    if not messages:
        raise ValueError("A user message is required")
    service = config.get("configurable", {}).get("knowledge_service")
    if service is None:
        service = get_query_service()
    # 图节点只适配输入输出，查询规划、检索和答案生成由同一个服务负责。
    response = await service.answer(message_text(messages[-1]), history=messages[:-1])
    return {"messages": [AIMessage(content=response.message)], "response": response.model_dump()}


builder = StateGraph(AgentState, input_schema=InputState)
builder.add_node("answer_knowledge", answer_knowledge)
builder.add_edge(START, "answer_knowledge")
builder.add_edge("answer_knowledge", END)
# HTTP 入口每轮从数据库恢复历史，不依赖单个进程的内存检查点维持会话。
graph = builder.compile()
