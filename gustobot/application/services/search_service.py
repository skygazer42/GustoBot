import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Sequence
from datetime import datetime

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.chat.chat_completion import Choice as ChatCompletionChoice
from pydantic import BaseModel, Field

from gustobot.application.prompts.search_prompts import (
    SEARCH_SUMMARY_PROMPT,
    SEARCH_SYSTEM_PROMPT,
)
from gustobot.config import settings
from gustobot.infrastructure.core.logger import get_logger
from gustobot.infrastructure.core.resources import close_on_exit
from gustobot.infrastructure.tools import get_tool, list_openai_tools, list_tool_specs

logger = get_logger(service="search")


class _SearchArguments(BaseModel):
    """Validated search-tool arguments returned by model tool selection."""

    query: str = Field(min_length=1, pattern=r"\S")
    num_results: int | None = Field(default=None, ge=1, le=10)


class SearchService:
    """Provide bounded web-search results through the configured search API."""

    def __init__(self):
        logger.info("Initializing SearchService...")
        self.client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
        )
        self.model = settings.OPENAI_MODEL
        self.search_tool = get_tool("search")

        self._tool_specs = list_tool_specs()
        self._openai_tools = list_openai_tools()

        self.tools_description = self._generate_tools_description()

    def _generate_tools_description(self) -> str:
        """根据工具定义生成工具描述提示"""
        tool_descriptions = []

        for spec in self._tool_specs:
            name = spec["name"]
            desc = spec.get("description", "")
            params = []

            param_schema = spec.get("parameters", {})
            required_params = param_schema.get("required", [])
            properties = param_schema.get("properties", {})
            if not isinstance(required_params, list) or not isinstance(properties, dict):
                # Reject invalid tool schema values before invoking a tool.
                raise ValueError(f"Invalid parameter schema for tool {name}")  # noqa: TRY004

            for param_name in required_params:
                param_info = properties.get(param_name, {})
                param_desc = param_info.get("description", "")
                if param_desc:
                    params.append(f"{param_name}，作用是：{param_desc}")

            tool_desc = (
                f"{name}，{desc}"
                f"{'，必须解析出来的参数是：' if params else ''}"
                f"{', '.join(params)}"
            )
            tool_descriptions.append(tool_desc)

        return "你现在可用的工具有：\n\n" + "\n".join(tool_descriptions)

    async def _call_with_tool(
        self,
        messages: Sequence["ChatCompletionMessageParam"],
    ) -> "ChatCompletionChoice":
        """调用模型并获取工具调用结果"""
        logger.info("Calling model for tool selection.")
        # get_logger returns Loguru; Ruff assumes stdlib formatting for this name.
        logger.debug("Selecting a tool for {} messages", len(messages))  # noqa: PLE1205

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            tools=self._openai_tools,
            tool_choice="auto",  # 让模型自己决定是否使用工具
            extra_body=settings.LLM_EXTRA_BODY,
        )

        logger.debug(  # noqa: PLE1205 - get_logger returns Loguru.
            "Model tool selection finished: {}", response.choices[0].finish_reason
        )
        return ChatCompletion.model_validate(response).choices[0]

    async def generate_stream(
        self,
        query: str,
        user_id: int | None = None,
        conversation_id: int | None = None,
        on_complete: Callable | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a direct answer or an answer grounded in search results."""
        messages: list[ChatCompletionMessageParam] = [
            {
                "role": "system",
                "content": SEARCH_SYSTEM_PROMPT.format(tools_description=self.tools_description),
            },
            {"role": "user", "content": query},
        ]
        choice = await self._call_with_tool(messages)
        direct_answer = choice.finish_reason == "stop"
        if choice.finish_reason == "tool_calls":
            tool_calls = choice.message.tool_calls
            if not tool_calls or tool_calls[0].type != "function":
                raise ValueError("Search response must include a function tool call")
            tool_call = tool_calls[0]
            if tool_call.function.name != "search":
                raise ValueError("Search response requested an unsupported tool")
            arguments = _SearchArguments.model_validate_json(tool_call.function.arguments)
            search_query = arguments.query
            search_results = await asyncio.to_thread(
                self.search_tool.search,
                search_query,
                num_results=arguments.num_results,
            )
            yield f"data: {json.dumps({'type': 'search_start'}, ensure_ascii=False)}\n\n"
            search_data = {
                "type": "search_results",
                "total": len(search_results),
                "query": search_query,
                "results": [
                    {key: result[key] for key in ("title", "url", "snippet")}
                    for result in search_results
                ],
            }
            yield f"data: {json.dumps(search_data, ensure_ascii=False)}\n\n"
            if not search_results:
                return
            context = [
                f"来源：{result['title']}\n链接：{result['url']}\n内容：{result['snippet']}\n"
                for result in search_results
            ]
            context_prompt = SEARCH_SUMMARY_PROMPT.format(
                context="\n---\n".join(context),
                query=query,
                cur_date=datetime.now().strftime("%Y年%m月%d日"),
            )
            messages = [{"role": "system", "content": context_prompt}]
        elif direct_answer:
            yield f"data: {json.dumps({'type': 'direct_answer'}, ensure_ascii=False)}\n\n"
        else:
            raise RuntimeError(f"Unsupported model finish reason: {choice.finish_reason}")

        stream_response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            extra_body=settings.LLM_EXTRA_BODY,
        )
        full_response = []
        async with close_on_exit(stream_response.close):
            async for chunk in stream_response:
                if not chunk.choices or not chunk.choices[0].delta.content:
                    continue
                content = chunk.choices[0].delta.content
                if direct_answer:
                    full_response.append(content)
                    payload: object = {"type": "direct_content", "content": content}
                else:
                    payload = content
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        if direct_answer and on_complete and user_id is not None and conversation_id is not None:
            await on_complete(
                user_id,
                conversation_id,
                [{"role": "user", "content": query}],
                "".join(full_response),
            )

    async def close(self) -> None:
        """Close the underlying HTTP client and release its connection pool."""
        await self.client.close()
