"""A single knowledge workflow; ontology understanding owns retrieval planning."""

from typing import TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from gustobot.application.messages import message_text
from gustobot.application.services.knowledge_runtime import get_query_service


class InputState(TypedDict):
    messages: list[BaseMessage]


class AgentState(InputState, total=False):
    response: dict


async def answer_knowledge(state: AgentState, *, config: RunnableConfig):
    messages = state["messages"]
    if not messages:
        raise ValueError("A user message is required")
    service = config.get("configurable", {}).get("knowledge_service")
    if service is None:
        service = get_query_service()
    response = await service.answer(message_text(messages[-1]), history=messages[:-1])
    return {"messages": [AIMessage(content=response.message)], "response": response.model_dump()}


builder = StateGraph(AgentState, input_schema=InputState)
builder.add_node("answer_knowledge", answer_knowledge)
builder.add_edge(START, "answer_knowledge")
builder.add_edge("answer_knowledge", END)
graph = builder.compile()
