"""Helpers for deterministic knowledge-base source provenance."""

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_source(document: Mapping[str, Any], backend: str) -> Dict[str, str]:
    """Build a stable source object from one retrieval result.

    The storage backend and the original data source are intentionally separate:
    ``backend`` explains where retrieval happened, while ``source`` identifies the
    file, table, or URL from which the indexed content originated.
    """

    metadata_value = document.get("metadata")
    metadata = metadata_value if isinstance(metadata_value, Mapping) else {}
    backend_name = backend.lower().strip()

    document_id = _text(
        document.get("document_id")
        or document.get("source_id")
        or document.get("id")
        or metadata.get("chunk_id")
        or metadata.get("id")
    )
    title = _text(
        document.get("name")
        or document.get("title")
        or metadata.get("name")
        or metadata.get("title")
        or metadata.get("菜品名称")
        or metadata.get("菜名")
    )
    url = _text(document.get("url") or metadata.get("url"))

    if backend_name == "postgres":
        # pgvector's generic search API historically used ``source`` for a row
        # identifier. Prefer the file/table fields so the UI does not mistake a
        # row ID for the original data source.
        source = _text(
            metadata.get("source_file")
            or metadata.get("ingest_source")
            or document.get("source_file")
            or document.get("source_table")
            or metadata.get("source_table")
            or metadata.get("source")
            or document.get("source")
            or document_id
        )
    elif backend_name == "milvus":
        # Existing Milvus collections do not persist the arbitrary ``source``
        # metadata field, but bootstrap ingestion stores it as ``recipe_id``.
        source = _text(
            document.get("source")
            or metadata.get("source")
            or metadata.get("source_file")
            or metadata.get("recipe_id")
            or title
            or document_id
        )
    else:
        source = _text(
            url
            or document.get("source")
            or metadata.get("source")
            or document.get("source_table")
            or metadata.get("source_table")
            or title
            or document_id
        )

    result = {"backend": backend_name or "unknown"}
    if source:
        result["source"] = source
    if document_id:
        result["document_id"] = document_id
    if title and title != source:
        result["name"] = title
    if url:
        result["url"] = url
    return result


def collect_sources(
    result_sets: Sequence[Tuple[str, Iterable[Mapping[str, Any]]]],
) -> List[Dict[str, str]]:
    """Collect and de-duplicate structured sources without losing order."""

    collected: List[Dict[str, str]] = []
    seen = set()
    for backend, documents in result_sets:
        for document in documents or []:
            if not isinstance(document, Mapping):
                continue
            source = build_source(document, backend)
            if len(source) == 1:  # only the backend is known
                continue
            key = (
                source.get("backend", ""),
                source.get("document_id", ""),
                source.get("source", ""),
                source.get("url", ""),
            )
            if key in seen:
                continue
            seen.add(key)
            collected.append(source)
    return collected


_GENERATED_SOURCE_SECTION = re.compile(
    r"\n\s*(?:"
    r"(?:[-*•]+\s*)?(?:\*{0,2})?"
    r"(?:参考资料|引用来源|资料来源|references)\s*[:：]\s*(?:\*{0,2})?"
    r"|"
    r"#{1,6}\s+(?:\*{0,2})?"
    r"(?:参考资料|引用来源|资料来源|references)(?:\*{0,2})?\s*[:：]?\s*"
    r").*\Z",
    flags=re.IGNORECASE | re.DOTALL,
)


def strip_generated_source_section(answer: str) -> str:
    """Remove a model-authored source footer.

    Source attribution is rendered from retrieval metadata. Removing a generated
    footer prevents the model from inventing backend labels such as
    ``[PostgreSQL#1]`` for a result that actually came from Milvus.
    """

    if not answer:
        return answer
    return _GENERATED_SOURCE_SECTION.sub("", answer).rstrip()
