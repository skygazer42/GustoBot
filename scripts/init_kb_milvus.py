"""
Utility script to seed the Milvus vector store with initial knowledge base text.
"""

import asyncio
import os
from pathlib import Path
from typing import Iterable

from loguru import logger

from gustobot.infrastructure.knowledge import KnowledgeService
from gustobot.infrastructure.core.resources import close_on_exit


async def _ingest_chunk(service: KnowledgeService, chunk: str, source_name: str, index: int) -> int:
    if not chunk.strip():
        return 0

    metadata = {
        "source": source_name,
        "ingest_mode": "bootstrap",
        "chunk_index": index,
    }
    result = await service.ingest_text(chunk, metadata=metadata)
    added = int(result["add_count"])
    logger.info("Milvus chunk {} ingested: {} segments", index, added)
    return added


def _chunk_paragraphs(paragraphs: Iterable[str], max_chars: int = 1600) -> list[str]:
    chunks: list[str] = []
    buffer: list[str] = []
    length = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if length + len(para) > max_chars and buffer:
            chunks.append("\n\n".join(buffer))
            buffer = []
            length = 0
        buffer.append(para)
        length += len(para) + 2

    if buffer:
        chunks.append("\n\n".join(buffer))

    return chunks


async def ingest_file(path: Path) -> int:
    if not path.exists():
        logger.warning("KB data file not found: {}", path)
        return 0

    content = (await asyncio.to_thread(path.read_text, encoding="utf-8")).strip()
    if not content:
        logger.warning("KB data file is empty: {}", path)
        return 0

    paragraphs = [p for p in content.split("\n\n") if p.strip()]
    chunks = _chunk_paragraphs(paragraphs)
    service = await asyncio.to_thread(KnowledgeService)
    total_added = 0
    failed_chunks = 0
    async with close_on_exit(service.close):
        for idx, chunk in enumerate(chunks, start=1):
            try:
                total_added += await _ingest_chunk(service, chunk, path.name, idx)
            except Exception as exc:
                failed_chunks += 1
                logger.exception("Failed to ingest chunk {}: {}", idx, exc)
    if failed_chunks:
        raise RuntimeError(
            f"Milvus ingestion incomplete: {failed_chunks}/{len(chunks)} chunks failed"
        )
    logger.info("Milvus ingestion finished: total {} segments", total_added)
    return total_added


async def main() -> int:
    data_path = Path(os.getenv("KB_DATA_FILE", "/app/data/kb/data.txt"))
    return await ingest_file(data_path)


if __name__ == "__main__":
    asyncio.run(main())
