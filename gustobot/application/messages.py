"""Extract text at the shared application boundary for model messages."""

from langchain_core.messages import BaseMessage


def message_text(message: BaseMessage) -> str:
    """Read text and text blocks without coercing arbitrary multimodal payloads."""
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif block.get("type") == "text":
            text = block["text"]
            if not isinstance(text, str):
                raise TypeError("Message text blocks must contain text")
            parts.append(text)
    return "".join(parts)
