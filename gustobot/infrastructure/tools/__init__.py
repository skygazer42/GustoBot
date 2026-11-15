"""
Unified access to application tools.
"""

from functools import lru_cache
from typing import Any, List

from openai.types.chat import ChatCompletionToolParam
from openai.types.shared_params import FunctionDefinition

from .definitions import ToolSpec, registry
from .search import SearchTool

# Register built-in tools.
registry.register(
    ToolSpec(
        name="search",
        description="使用 SerpAPI 执行 Google 搜索以获取最新的公开信息",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用于检索的关键词或问题",
                },
                "num_results": {
                    "type": "integer",
                    "description": "需要返回的结果数量",
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["query"],
        },
    ),
    SearchTool,
)


def list_tool_specs() -> List[FunctionDefinition]:
    """
    Return tool function definitions formatted for OpenAI function calling.
    """
    return [spec.as_openai_function() for spec in registry.get_specs()]


def get_tool_spec(name: str) -> FunctionDefinition:
    """
    Retrieve a single tool spec formatted for OpenAI function calling.
    """
    return registry.get_spec(name).as_openai_function()


def list_openai_tools() -> List[ChatCompletionToolParam]:
    """
    Return tool entries suitable for the OpenAI `tools` argument.
    """
    return [spec.as_openai_tool() for spec in registry.get_specs()]


@lru_cache(maxsize=None)
def get_tool(name: str) -> Any:
    """
    Instantiate and cache a tool by name.
    """
    return registry.create(name)
