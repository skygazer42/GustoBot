"""Preserve state construction under the supported Python 3.9 dataclass API."""

import dataclasses
from pathlib import Path
import runpy

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph


@pytest.mark.parametrize(
    "relative_path",
    [
        "gustobot/application/agents/lg_states.py",
    ],
)
def test_state_constructors_preserve_dataclass_and_keyword_contract(monkeypatch, relative_path):
    real_dataclass = dataclasses.dataclass

    def python39_dataclass(*args, **kwargs):
        unsupported = set(kwargs) & {"kw_only", "slots", "match_args"}
        if unsupported:
            raise TypeError(f"Python 3.9 dataclass does not accept {unsupported}")
        return real_dataclass(*args, **kwargs)

    monkeypatch.setattr(dataclasses, "dataclass", python39_dataclass)
    root = Path(__file__).resolve().parents[1]
    module_name = relative_path.removesuffix(".py").replace("/", ".")
    namespace = runpy.run_path(str(root / relative_path), run_name=module_name)
    state_name = "AgentState" if "AgentState" in namespace else "ResearcherState"
    state_type = namespace[state_name]
    required_name = "messages" if state_name == "AgentState" else "question"
    value = [HumanMessage(content="recipe")] if required_name == "messages" else "recipe"

    first = state_type(**{required_name: value})
    second = state_type(**{required_name: value})
    assert dataclasses.is_dataclass(type(first))
    assert required_name in {field.name for field in dataclasses.fields(first)}
    # The entrypoint is loaded dynamically so each exported state is exercised.
    first.documents.append("first-only")
    assert second.documents == []
    with pytest.raises(TypeError):
        state_type(value)
    with pytest.raises(TypeError):
        state_type()

    builder = StateGraph(state_type)
    builder.add_node("respond", lambda state: {"documents": ["recipe"]})
    builder.add_edge(START, "respond")
    builder.add_edge("respond", END)
    documents = builder.compile().invoke(second)["documents"]
    assert len(documents) == 1
    if state_name == "ResearcherState":
        assert isinstance(documents[0], Document)
        assert documents[0].page_content == "recipe"
    else:
        assert documents == ["recipe"]
