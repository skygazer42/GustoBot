"""Terminal client for the same unified knowledge service used by HTTP."""

import asyncio

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from gustobot.application.services.knowledge_runtime import (
    cleanup_runtime,
    get_query_service,
)


async def main() -> None:
    history: list[BaseMessage] = []
    try:
        while True:
            question = await asyncio.to_thread(input, "> ")
            if question.strip().lower() in {"q", "quit", "exit"}:
                break
            answer = await get_query_service().answer(question, history=history)
            print(answer.message)
            history.extend(
                [
                    HumanMessage(content=question),
                    AIMessage(
                        content=answer.message,
                        additional_kwargs={
                            "knowledge_choices": answer.metadata.get("choices", []),
                            "knowledge_plan": answer.metadata.get("plan"),
                        },
                    ),
                ]
            )
    finally:
        await cleanup_runtime()


if __name__ == "__main__":
    asyncio.run(main())
