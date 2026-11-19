"""
知识库模块
Knowledge Base Module
"""

from importlib import import_module


def __getattr__(name: str):
    modules = {
        "VectorStore": ".vector_store",
        "KnowledgeService": ".knowledge_service",
        "Reranker": ".reranker",
    }
    if name not in modules:
        raise AttributeError(name)
    return getattr(import_module(modules[name], __name__), name)


__all__ = [
    "KnowledgeService",
    "Reranker",
    "VectorStore",
]
