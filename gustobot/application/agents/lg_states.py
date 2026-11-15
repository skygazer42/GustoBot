from pydantic import BaseModel, ConfigDict, Field
from dataclasses import dataclass, field
from typing import Annotated, Literal, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class Router(BaseModel):
    """Classify a user query for the supervisor graph."""

    logic: str = ""
    type: Literal[
        "general-query",
        "additional-query",
        "kb-query",
        "graphrag-query",
        "image-query",
        "file-query",
        "text2sql-query",
    ] = "kb-query"
    question: str = ""
    decision: Optional[str] = None
    confidence: Optional[float] = None
    reasoning: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class GradeHallucinations(BaseModel):
    """Binary score for hallucination present in generation answer."""

    binary_score: str = Field(description="Answer is grounded in the facts, '1' or '0'")


@dataclass(init=False)
class InputState:
    """Represents the input state for the agent.

    This class defines the structure of the input state, which includes
    the messages exchanged between the user and the agent.
    """

    messages: Annotated[list[BaseMessage], add_messages]

    def __init__(self, *, messages: list[BaseMessage]) -> None:
        self.messages = messages


@dataclass(init=False)
class AgentState(InputState):
    """State of the retrieval graph / agent."""

    router: Router = field(default_factory=lambda: Router(type="general-query", logic=""))
    """The router's classification of the user's query."""
    steps: list[str] = field(default_factory=list)
    """Populated by the retriever. This is a list of documents that the agent can reference."""
    documents: list[str] = field(default_factory=list)
    """Documents retrieved from the knowledge base."""
    question: str = field(default_factory=str)
    answer: str = field(default_factory=str)
    hallucination: GradeHallucinations = field(
        default_factory=lambda: GradeHallucinations(binary_score="0")
    )
    sources: list = field(default_factory=list)
    """Sources from knowledge base queries."""

    def __init__(
        self,
        *,
        messages: list[BaseMessage],
        router: Optional[Router] = None,
        steps: Optional[list[str]] = None,
        documents: Optional[list[str]] = None,
        question: str = "",
        answer: str = "",
        hallucination: Optional[GradeHallucinations] = None,
        sources: Optional[list] = None,
    ) -> None:
        super().__init__(messages=messages)
        self.router = Router(type="general-query", logic="") if router is None else router
        self.steps = [] if steps is None else steps
        self.documents = [] if documents is None else documents
        self.question = question
        self.answer = answer
        self.hallucination = (
            GradeHallucinations(binary_score="0") if hallucination is None else hallucination
        )
        self.sources = [] if sources is None else sources
