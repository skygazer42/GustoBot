"""
测试 LightRAG Node 的初始化和基本功能
"""

import asyncio
import logging
from dotenv import load_dotenv

from gustobot.infrastructure.core.resources import close_on_exit

logger = logging.getLogger("test-lightrag")


async def test_initialization():
    """测试初始化；成功后将 API 的关闭责任交给调用方。"""
    from gustobot.application.services.lightrag_service import LightRAGService

    logger.info("=" * 50)
    logger.info("测试 LightRAG 初始化")
    logger.info("=" * 50)

    # 创建 LightRAG API 实例
    lightrag_api = LightRAGService(
        working_dir="./test_lightrag_data",
        default_mode="hybrid",
        default_top_k=5,
    )

    # 初始化
    logger.info("开始初始化 LightRAG...")
    try:
        await lightrag_api.initialize()
    except BaseException:
        async with close_on_exit(lightrag_api.cleanup):
            raise
    logger.info("LightRAG 初始化成功")

    return lightrag_api


async def test_embedding():
    """测试 Embedding 函数"""
    logger.info("\n" + "=" * 50)
    logger.info("测试 Embedding 函数")
    logger.info("=" * 50)

    lightrag_api = await test_initialization()
    async with close_on_exit(lightrag_api.cleanup):
        # 测试 embedding
        test_texts = ["这是一个测试文本", "红烧肉的做法", "如何制作宫保鸡丁"]
        logger.info(f"测试文本: {test_texts}")

        rag = lightrag_api.rag
        if rag is None:
            raise RuntimeError("LightRAG initialization did not establish a runtime")
        embeddings = await rag.embedding_func(test_texts)
        logger.info("Embedding 成功")
        logger.info(f"  - 向量维度: {len(embeddings[0])}")
        logger.info(f"  - 向量数量: {len(embeddings)}")


async def test_insert_document():
    """测试插入文档"""
    logger.info("\n" + "=" * 50)
    logger.info("测试插入文档")
    logger.info("=" * 50)

    lightrag_api = await test_initialization()
    async with close_on_exit(lightrag_api.cleanup):
        # 测试文档
        test_doc = """
    红烧肉是一道经典的中华料理，以五花肉为主要食材。

    主要食材：
    - 五花肉 500克
    - 冰糖 30克
    - 生抽 2勺
    - 老抽 1勺
    - 料酒 2勺

    制作步骤：
    1. 将五花肉切成2厘米见方的块状
    2. 冷水下锅，焯水去除血沫
    3. 锅中放少许油，放入冰糖炒糖色
    4. 加入五花肉翻炒上色
    5. 加入生抽、老抽、料酒
    6. 加水没过肉，大火烧开后转小火炖1小时
    7. 大火收汁即可

    烹饪技巧：
    - 糖色不要炒过头，否则会发苦
    - 炖煮时间要足够，肉质才会软烂
    - 最后收汁要用大火，让汁水浓稠
    """

        logger.info("插入测试文档...")
        result = await lightrag_api.insert_documents([test_doc])
        logger.info("文档插入成功")
        logger.info(f"  - 成功: {result.success}")
        logger.info(f"  - 失败: {result.failed}")


async def test_query():
    """测试查询功能"""
    from gustobot.application.services.lightrag_service import LightRAGService

    logger.info("\n" + "=" * 50)
    logger.info("测试查询功能")
    logger.info("=" * 50)

    # 先插入文档
    await test_insert_document()

    # 创建新的 API 实例进行查询
    lightrag_api = LightRAGService(
        working_dir="./test_lightrag_data",
        default_mode="hybrid",
        default_top_k=5,
    )
    async with close_on_exit(lightrag_api.cleanup):
        await lightrag_api.initialize()

        # 测试查询
        query = "红烧肉怎么做？"
        logger.info(f"查询: {query}")

        result = await lightrag_api.query(query, mode="hybrid")
        logger.info("查询成功")
        logger.info("  - 查询模式: hybrid")
        logger.info(f"  - 响应长度: {len(result)} 字符")
        logger.info(f"\n响应内容:\n{result[:500]}...")


async def test_second_working_directory():
    """测试独立工作目录"""
    from gustobot.application.services.lightrag_service import LightRAGService

    logger.info("\n" + "=" * 50)
    logger.info("测试独立工作目录")
    logger.info("=" * 50)

    # 创建独立工作目录的实例
    lightrag_api = LightRAGService(
        working_dir="./test_lightrag",
        default_mode="hybrid",
        default_top_k=5,
    )

    async with close_on_exit(lightrag_api.cleanup):
        logger.info("初始化独立的 LightRAG 工作目录...")
        await lightrag_api.initialize()
        logger.info("独立 LightRAG 工作目录初始化成功")


async def main():
    """运行所有测试"""
    logger.info("开始测试 LightRAG Node 实现\n")

    # 测试 1: 初始化
    api = await test_initialization()
    await api.cleanup()

    # 测试 2: Embedding
    await test_embedding()

    # 测试 3: 插入文档和查询
    await test_query()

    # 测试 4: 独立工作目录 (可选)
    await test_second_working_directory()

    logger.info("\n" + "=" * 50)
    logger.info("所有测试完成")
    logger.info("=" * 50)


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
