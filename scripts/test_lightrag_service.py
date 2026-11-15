"""
测试 LightRAG 服务

验证基于预生成索引文件的问答检索功能
"""

import asyncio
from pathlib import Path
import sys
from typing import TYPE_CHECKING, List

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

if TYPE_CHECKING:
    from gustobot.application.services.lightrag_service import LightRAGService


async def print_stream(stream):
    """打印流式响应"""
    async for chunk in stream:
        print(chunk, end="", flush=True)
    print("\n")


async def test_query_modes(service: "LightRAGService"):
    """测试所有查询模式"""
    from gustobot.application.services.lightrag_service import (
        SearchMode,
    )

    # 初始化服务
    await service.initialize()

    # 测试查询
    test_query = "红烧肉怎么做？"

    print("LightRAG 服务测试")

    # 测试各种模式
    modes: List[SearchMode] = ["naive", "local", "global", "hybrid"]

    for mode in modes:
        print(f"Query mode: {mode}")

        # 非流式查询
        response = await service.query(
            query=test_query,
            mode=mode,
            stream=False,
        )
        print(f"\n回答:\n{response[:500]}...")  # 只显示前 500 字符
        print(f"\n完整响应长度: {len(response)} 字符")


async def test_stream_query(service: "LightRAGService"):
    """测试流式查询"""
    await service.initialize()

    print("流式查询测试 (hybrid mode)")

    response = await service.query(
        query="宫保鸡丁的做法",
        mode="hybrid",
        stream=True,
    )

    from gustobot.infrastructure.core.resources import close_on_exit

    async with close_on_exit(response.aclose):
        await print_stream(response)


async def test_structured_query(service: "LightRAGService"):
    """测试结构化查询"""
    from gustobot.application.services.lightrag_service import (
        LightRAGQueryRequest,
    )

    await service.initialize()

    print("结构化查询测试")

    request = LightRAGQueryRequest(
        query="麻婆豆腐怎么做？",
        mode="hybrid",
        top_k=5,
        stream=False,
    )

    response = await service.query_structured(request)

    print(f"\n原始查询: {response.query}")
    print(f"检索模式: {response.mode}")
    print(f"元数据: {response.metadata}")
    print(f"\n回答:\n{response.response[:500]}...")


async def test_index_stats(service: "LightRAGService"):
    """测试索引统计"""
    print("索引文件统计")

    stats = service.get_index_stats()

    print(f"\n工作目录: {stats['working_dir']}")
    print(f"总大小: {stats['total_size_mb']} MB")
    print(f"已初始化: {stats['initialized']}")
    print("\n文件详情:")

    for file_name, file_info in stats["files"].items():
        status = "存在" if file_info["exists"] else "缺失"
        size = f"{file_info['size_mb']} MB" if file_info["exists"] else "N/A"
        print(f"  {status} {file_name}: {size}")


async def main():
    """主测试函数"""
    from gustobot.infrastructure.core.resources import close_on_exit

    from gustobot.application.services.lightrag_service import LightRAGService
    from gustobot.config import settings

    service = LightRAGService(
        default_mode=settings.LIGHTRAG_RETRIEVAL_MODE,
        default_top_k=settings.LIGHTRAG_TOP_K,
    )
    async with close_on_exit(service.cleanup):
        await test_index_stats(service)
        await test_query_modes(service)
        await test_stream_query(service)
        await test_structured_query(service)
        print("所有测试完成")


if __name__ == "__main__":
    asyncio.run(main())
