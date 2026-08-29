"""Regression tests for deterministic KB source attribution."""

import asyncio

from gustobot.application.agents.kb_tools.node import create_knowledge_query_node
from gustobot.application.agents.kb_tools.sources import (
    build_source,
    collect_sources,
    strip_generated_source_section,
)


def test_milvus_source_uses_dataset_identity_instead_of_chunk_id() -> None:
    source = build_source(
        {
            "id": "data.txt_1",
            "metadata": {"recipe_id": "data.txt", "name": ""},
        },
        "milvus",
    )

    assert source == {
        "backend": "milvus",
        "source": "data.txt",
        "document_id": "data.txt_1",
    }


def test_postgres_source_prefers_ingested_file_over_row_identifier() -> None:
    source = build_source(
        {
            "id": "42",
            "document_id": "0",
            "source_id": "0",
            "source_table": "Sheet1",
            "source": "0",
            "metadata": {
                "source_file": "历史菜谱源头.xlsx",
                "菜品名称": "红烧肉",
            },
        },
        "postgres",
    )

    assert source["backend"] == "postgres"
    assert source["source"] == "历史菜谱源头.xlsx"
    assert source["document_id"] == "0"
    assert source["name"] == "红烧肉"


def test_collect_sources_preserves_backend_and_deduplicates_exact_hits() -> None:
    milvus_hit = {"id": "data.txt_1", "metadata": {"recipe_id": "data.txt"}}
    postgres_hit = {
        "document_id": "1",
        "source_table": "Sheet1",
        "metadata": {"source_file": "历史菜谱源头.xlsx"},
    }

    sources = collect_sources(
        [
            ("milvus", [milvus_hit, milvus_hit]),
            ("postgres", [postgres_hit]),
        ]
    )

    assert sources == [
        {
            "backend": "milvus",
            "source": "data.txt",
            "document_id": "data.txt_1",
        },
        {
            "backend": "postgres",
            "source": "历史菜谱源头.xlsx",
            "document_id": "1",
        },
    ]


def test_generated_source_footer_is_removed_from_answer() -> None:
    answer = (
        "火锅在不同朝代形成了多种吃法。\n\n"
        "**参考资料：** [PostgreSQL#1]、[PostgreSQL#2]"
    )

    assert strip_generated_source_section(answer) == "火锅在不同朝代形成了多种吃法。"


def test_generated_markdown_source_section_is_removed_from_answer() -> None:
    answer = "正文。\n\n### References\n- [Milvus#1]"

    assert strip_generated_source_section(answer) == "正文。"


def test_inline_source_word_is_not_removed() -> None:
    answer = "用户询问了参考资料是否可靠，答案应说明需进一步核验。"

    assert strip_generated_source_section(answer) == answer


def test_direct_kb_node_returns_structured_source_and_cleans_answer() -> None:
    class KnowledgeServiceStub:
        async def search(self, **_kwargs):
            return [
                {
                    "id": "data.txt_3",
                    "content": "一段可检索的历史资料",
                    "score": 0.9,
                    "metadata": {"recipe_id": "data.txt"},
                }
            ]

    class LLMClientStub:
        async def chat(self, **_kwargs):
            return "可靠回答。\n\n参考资料：[PostgreSQL#1]"

    node = create_knowledge_query_node(
        knowledge_service=KnowledgeServiceStub(),
        llm_client=LLMClientStub(),
    )
    result = asyncio.run(node({"task": "测试问题", "context": {}, "steps": []}))

    assert result["answer"] == "可靠回答。"
    assert result["sources"] == [
        {
            "backend": "milvus",
            "source": "data.txt",
            "document_id": "data.txt_3",
        }
    ]
