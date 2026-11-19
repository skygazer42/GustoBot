"""Offline contracts for the second Agent/RAG conformance pass."""


def test_multimodal_user_message_preserves_text_blocks():
    from langchain_core.messages import HumanMessage

    from gustobot.application.messages import message_text

    message = HumanMessage(
        content=[
            {"type": "text", "text": "How to cook "},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            {"type": "text", "text": "this dish?"},
        ]
    )
    assert message_text(message) == "How to cook this dish?"
