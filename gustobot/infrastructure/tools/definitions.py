from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from openai.types.chat import ChatCompletionToolParam
from openai.types.shared_params import FunctionDefinition


@dataclass(frozen=True)
class ToolSpec:
    """Describe a tool so it can be surfaced to LLMs."""

    name: str
    description: str
    parameters: dict[str, object] = field(default_factory=dict)

    def as_openai_function(self) -> FunctionDefinition:
        """
        Return the spec formatted for OpenAI function calling.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def as_openai_tool(self) -> ChatCompletionToolParam:
        """
        Return the spec wrapped in the format expected by OpenAI `tools`.
        """
        return {
            "type": "function",
            "function": self.as_openai_function(),
        }


class ToolRegistry:
    """Keep track of tool specifications and factories."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._factories: dict[str, Callable[[], Any]] = {}

    def register(self, spec: ToolSpec, factory: Callable[[], Any]) -> None:
        """Register one model-visible tool specification and its lazy factory."""
        self._specs[spec.name] = spec
        self._factories[spec.name] = factory

    def get_spec(self, name: str) -> ToolSpec:
        """Return a registered tool specification by its name."""
        return self._specs[name]

    def get_specs(self) -> Iterable[ToolSpec]:
        """Return the registered tool specifications without copying them."""
        return self._specs.values()

    def has_tool(self, name: str) -> bool:
        """Check whether a tool name has a registered specification."""
        return name in self._specs

    def create(self, name: str) -> Any:
        """Instantiate a registered tool through its factory."""
        factory = self._factories.get(name)
        if factory is None:
            raise KeyError(f"No tool registered under name '{name}'")
        return factory()


registry = ToolRegistry()
