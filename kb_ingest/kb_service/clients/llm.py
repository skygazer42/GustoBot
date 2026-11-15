import logging
import os
from enum import Enum
from typing import List, Optional

import requests
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field

from kb_service.core.config import Config

logger = logging.getLogger(__name__)


class _OllamaResponse(BaseModel):
    response: str


class _ChatMessage(BaseModel):
    content: str


class _ChatChoice(BaseModel):
    message: _ChatMessage


class _ChatResponse(BaseModel):
    choices: List[_ChatChoice] = Field(min_length=1)


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    QWEN = "qwen"
    OLLAMA = "ollama"
    GLM = "glm"


class LLMClient:
    """Provider-agnostic interface for generating rewritten text."""

    def __init__(self, config: Config):
        self.config = config
        self.provider = LLMProvider(config.llm_provider.lower())
        self._setup_client()

    def _setup_client(self) -> None:
        if self.provider in (LLMProvider.OPENAI, LLMProvider.QWEN):
            api_key = self.config.llm_api_key or os.getenv("OPENAI_API_KEY")
            base_url: Optional[str]
            if self.provider == LLMProvider.OPENAI:
                base_url = self.config.llm_base_url
            else:
                api_key = api_key or "EMPTY"
                base_url = (
                    self.config.llm_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
                )

            self.openai_client = OpenAI(api_key=api_key, base_url=base_url)

        elif self.provider == LLMProvider.OLLAMA:
            base_url = self.config.llm_base_url or "http://localhost:11434"
            self.ollama_url = f"{base_url.rstrip('/')}/api/generate"

        elif self.provider == LLMProvider.GLM:
            self.glm_api_key = self.config.llm_api_key or os.getenv("GLM_API_KEY")

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        try:
            if self.provider in (LLMProvider.OPENAI, LLMProvider.QWEN):
                return self._generate_openai(prompt, system_prompt)
            if self.provider == LLMProvider.OLLAMA:
                return self._generate_ollama(prompt, system_prompt)
            if self.provider == LLMProvider.GLM:
                return self._generate_glm(prompt, system_prompt)
        except Exception as exc:
            logger.exception("LLM generation failed")
            raise RuntimeError(f"LLM generate failed: {exc}") from exc
        raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _generate_openai(self, prompt: str, system_prompt: str) -> str:
        messages: List[ChatCompletionMessageParam] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        completion = self.openai_client.chat.completions.create(
            model=self.config.llm_model,
            messages=messages,
            temperature=self.config.llm_temperature,
        )
        content = completion.choices[0].message.content
        if content is None:
            raise ValueError("LLM response contains no text content")
        return content.strip()

    def _generate_ollama(self, prompt: str, system_prompt: str) -> str:
        payload = {
            "model": self.config.llm_model,
            "prompt": f"{system_prompt}\n{prompt}" if system_prompt else prompt,
            "stream": False,
            "temperature": self.config.llm_temperature,
        }
        with requests.post(self.ollama_url, json=payload, timeout=60) as resp:
            resp.raise_for_status()
            data = resp.json()
        return _OllamaResponse.model_validate(data).response.strip()

    def _generate_glm(self, prompt: str, system_prompt: str) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.glm_api_key}",
        }
        data = {
            "model": self.config.llm_model,
            "messages": messages,
            "temperature": self.config.llm_temperature,
        }
        with requests.post(
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            headers=headers,
            json=data,
            timeout=60,
        ) as resp:
            resp.raise_for_status()
            payload = resp.json()
        return _ChatResponse.model_validate(payload).choices[0].message.content.strip()

    def close(self) -> None:
        if self.provider in (LLMProvider.OPENAI, LLMProvider.QWEN):
            self.openai_client.close()
