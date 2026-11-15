#!/usr/bin/env python3
"""
导入历史饮食文化数据到Milvus
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
TEXT_FILE = PROJECT_ROOT / "data" / "kb" / "data.txt"


async def import_history_text() -> None:
    """导入data.txt到Milvus"""
    from gustobot.infrastructure.knowledge import KnowledgeService
    from gustobot.infrastructure.core.resources import close_on_exit

    content = await asyncio.to_thread(TEXT_FILE.read_text, encoding="utf-8")
    service = await asyncio.to_thread(KnowledgeService)

    async with close_on_exit(service.close):
        # 分段处理
        paragraphs = []
        lines = content.split("\n")
        current_paragraph = ""

        for line in lines:
            line = line.strip()
            if line and not line.startswith(
                (
                    "1.",
                    "2.",
                    "3.",
                    "4.",
                    "5.",
                    "6.",
                    "7.",
                    "8.",
                    "9.",
                    "10.",
                    "11.",
                    "12.",
                    "13.",
                    "14.",
                    "15.",
                    "16.",
                    "17.",
                    "18.",
                    "19.",
                    "20.",
                )
            ):
                current_paragraph += line + " "
            else:
                if current_paragraph.strip():
                    paragraphs.append(current_paragraph.strip())
                if line and not line.endswith(("。", "！", "？")):
                    current_paragraph = line + " "
                else:
                    current_paragraph = line

        if current_paragraph.strip():
            paragraphs.append(current_paragraph.strip())

        # 过滤空段落和过短的段落
        paragraphs = [p for p in paragraphs if len(p) > 20]

        print(f"准备导入 {len(paragraphs)} 个段落")

        # 逐个添加文档
        success_count = 0
        for i, paragraph in enumerate(paragraphs[:50], 1):  # 限制前50个段落
            doc_id = f"history_{i:03d}"
            title = f"中国饮食文化历史资料 - 第{i}段"

            success = await service.add_document(
                doc_id=doc_id,
                title=title,
                content=paragraph,
                metadata={"source": "data.txt", "category": "历史文化", "paragraph_index": i},
            )

            if success:
                success_count += 1
                print(f"成功导入段落 {i}")
            else:
                print(f"导入段落 {i} 失败")

        print(f"\n导入完成！成功导入 {success_count}/{len(paragraphs[:50])} 个段落")


if __name__ == "__main__":
    asyncio.run(import_history_text())
