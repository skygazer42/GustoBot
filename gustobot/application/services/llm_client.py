"""
Lightweight wrapper for OpenAI-compatible chat completions.
"""

import json
from collections.abc import Sequence
from typing import Any

from loguru import logger
from openai import AsyncOpenAI, BadRequestError
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.shared_params.response_format_json_object import (
    ResponseFormatJSONObject,
)

from gustobot.config import settings

ChatMessage = dict[str, str]


class LLMClient:
    """Async helper around chat completions."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
    ) -> None:
        self.api_key = settings.OPENAI_API_KEY if api_key is None else api_key
        self.base_url = settings.OPENAI_API_BASE if base_url is None else base_url
        self.model = settings.OPENAI_MODEL if model is None else model
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if self.base_url is not None and not self.base_url.strip():
            raise ValueError("base_url must be a URL or None for the SDK default")
        self.default_temperature = temperature

        self._client: AsyncOpenAI | None = None
        if self.api_key:
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        else:
            logger.warning("LLMClient initialised without OPENAI_API_KEY; LLM features disabled.")

    def _ensure_client(self) -> AsyncOpenAI:
        if self._client is None:
            raise RuntimeError("LLM client is not configured. Provide OPENAI_API_KEY to enable it.")
        return self._client

    @staticmethod
    def _format_messages(
        system_prompt: str | None,
        user_message: str,
        context: Sequence[ChatMessage] | None = None,
    ) -> list[ChatCompletionMessageParam]:
        messages: list[ChatCompletionMessageParam] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if context:
            for item in context:
                role = item["role"]
                content = item["content"]
                if role == "user" and content:
                    messages.append({"role": "user", "content": content})
                elif role == "assistant" and content:
                    messages.append({"role": "assistant", "content": content})

        messages.append({"role": "user", "content": user_message})
        return messages

    async def complete(
        self,
        *,
        messages: Sequence[ChatCompletionMessageParam],
        temperature: float,
        response_format: ResponseFormatJSONObject | None = None,
    ) -> ChatCompletion:
        """Call the chat completion endpoint."""
        client = self._ensure_client()
        if response_format is None:
            return await client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                temperature=temperature,
                extra_body=settings.LLM_EXTRA_BODY,
            )
        return await client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            temperature=temperature,
            response_format=response_format,
            extra_body=settings.LLM_EXTRA_BODY,
        )

    async def chat(
        self,
        *,
        system_prompt: str | None,
        user_message: str,
        context: Sequence[ChatMessage] | None = None,
        temperature: float | None = None,
    ) -> str:
        """Return the assistant message content."""
        messages = self._format_messages(system_prompt, user_message, context)
        response = await self.complete(
            messages=messages,
            temperature=temperature if temperature is not None else self.default_temperature,
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("LLM response contains no text content")
        return content

    async def chat_json(
        self,
        *,
        system_prompt: str | None,
        user_message: str,
        context: Sequence[ChatMessage] | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Request a JSON object response and parse it."""
        messages = self._format_messages(system_prompt, user_message, context)
        try:
            response = await self.complete(
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except BadRequestError as exc:
            message = exc.message.lower()
            if "response_format" not in message or not any(
                reason in message
                for reason in ("not support", "unsupported", "unknown parameter", "unrecognized")
            ):
                raise
            logger.warning("Provider does not support response_format; requesting plain JSON.")
            response = await self.complete(messages=messages, temperature=temperature)

        content = response.choices[0].message.content
        if content is None:
            raise ValueError("LLM response contains no JSON content")
        payload = json.loads(content)
        if not isinstance(payload, dict):
            # Malformed model responses retain the adapter ValueError contract.
            raise ValueError("LLM JSON response must be an object")  # noqa: TRY004
        return payload

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
