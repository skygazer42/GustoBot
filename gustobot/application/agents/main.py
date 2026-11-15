import os
from typing import Any, List, Optional, Sequence, cast

from gustobot.application.agents.lg_states import InputState
from gustobot.application.agents.utils import new_uuid, message_text
from langchain_core.runnables import RunnableConfig
from gustobot.application.agents.lg_builder import graph
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import RemoveMessage
from langgraph.types import Command
import asyncio
import builtins

thread: RunnableConfig = {"configurable": {"thread_id": new_uuid()}}


def _resolve_memory_turn_limit() -> Optional[int]:
    """Resolve configured memory turns, treating non-positive values as unlimited."""
    raw_value = os.getenv("GUSTOBOT_MEMORY_TURNS", os.getenv("GUSTOBOT_MAX_MEMORY_TURNS", "2"))
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 5
    return value if value > 0 else None


MEMORY_TURN_LIMIT: Optional[int] = _resolve_memory_turn_limit()


def _select_messages_to_remove(existing: Sequence[BaseMessage]) -> List[BaseMessage]:
    """Determine which historical messages should be dropped to respect the turn limit."""
    if not existing or MEMORY_TURN_LIMIT is None:
        return []

    humans_to_keep = max(MEMORY_TURN_LIMIT - 1, 0)
    if humans_to_keep == 0:
        return [msg for msg in existing if msg.id is not None]

    humans_seen = 0
    keep_from = 0
    for index in range(len(existing) - 1, -1, -1):
        message = existing[index]
        if message.type == "human":
            humans_seen += 1
            if humans_seen == humans_to_keep:
                keep_from = index
                break
    else:
        keep_from = 0

    return [msg for msg in existing[:keep_from] if msg.id is not None]


async def process_query(query: str) -> None:
    state_snapshot = graph.get_state(thread)
    existing_messages = list(state_snapshot.values.get("messages", []))
    messages_to_remove = _select_messages_to_remove(existing_messages)

    removals = [RemoveMessage(id=msg.id) for msg in messages_to_remove if msg.id is not None]
    human_message = HumanMessage(content=query)
    input_messages: List[BaseMessage] = [*removals, human_message]
    input_state = InputState(messages=input_messages)

    async for event in graph.astream(
        input=input_state,
        stream_mode="messages",
        config=thread,
    ):
        # LangGraph's generic stream type does not specialize message events.
        chunk, metadata = cast(tuple[BaseMessage, dict[str, Any]], event)
        text = message_text(chunk)
        if text and "research_plan" not in metadata.get("tags", []):
            print(text, end="", flush=True)

    latest_snapshot = graph.get_state(thread)
    pending_tasks = latest_snapshot.tasks
    if pending_tasks and len(pending_tasks[0].interrupts) > 0:
        response = input('\n响应可能包含不确定信息。重试生成？如果是，按"y"：')
        if response.lower() == "y":
            async for event in graph.astream(
                Command(resume=response),
                stream_mode="messages",
                config=thread,
            ):
                chunk, metadata = cast(tuple[BaseMessage, dict[str, Any]], event)
                text = message_text(chunk)
                if text and "research_plan" not in metadata.get("tags", []):
                    await asyncio.sleep(0.05)
                    print(text, end="", flush=True)


async def main() -> None:
    input_func = builtins.input
    while True:
        query = input_func("> ")
        if query.strip().lower() == "q":
            print("Exiting...")
            break
        await process_query(query)


if __name__ == "__main__":
    asyncio.run(main())
