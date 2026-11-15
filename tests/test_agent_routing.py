"""
Agent 路由测试脚本

测试 LangGraph 多 Agent 系统的路由和智能决策功能
执行方式：python -m tests.test_agent_routing
"""

import os
import logging

if __name__ != "__main__" and not os.getenv("GUSTOBOT_RUN_INTEGRATION_TESTS"):
    import pytest

    pytest.skip(
        "Integration-style routing script "
        "(set GUSTOBOT_RUN_INTEGRATION_TESTS=1 to enable in pytest).",
        allow_module_level=True,
    )

import asyncio
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


logger = logging.getLogger("test_agent_routing")


class RoutingTestCase:
    """路由测试用例"""

    def __init__(
        self,
        question: str,
        expected_route: str,
        expected_node: str,
        description: str,
        sub_decision: Optional[str] = None,
        image_path: Optional[str] = None,
        file_path: Optional[str] = None,
    ):
        self.question = question
        self.expected_route = expected_route
        self.expected_node = expected_node
        self.description = description
        self.sub_decision = sub_decision
        self.image_path = image_path
        self.file_path = file_path


async def test_routing(
    test_case: RoutingTestCase, session_id: str = "test_session"
) -> Dict[str, Any]:
    """测试单个路由问题"""

    from langchain_core.messages import HumanMessage
    from langchain_core.runnables import RunnableConfig
    from gustobot.application.agents.lg_builder import graph
    from gustobot.application.agents.lg_states import InputState, Router
    from gustobot.application.agents.utils import message_text

    config: RunnableConfig = {
        "configurable": {
            "thread_id": session_id,
            "image_path": test_case.image_path,
            "file_path": test_case.file_path,
        }
    }

    input_state = InputState(messages=[HumanMessage(content=test_case.question)])

    try:
        result = await graph.ainvoke(input_state, config=config)

        router_info = result.get("router", {})
        if isinstance(router_info, Router):
            router_info = router_info.model_dump()
        actual_route = router_info.get("type", "unknown")
        actual_logic = router_info.get("logic", "")
        response_text = message_text(result["messages"][-1]) if result.get("messages") else ""

        # 验证结果
        route_match = actual_route == test_case.expected_route
        status = "PASS" if route_match else "FAIL"

        logger.info(f"\n{'='*80}")
        logger.info(f"测试: {test_case.description}")
        logger.info(f"问题: {test_case.question}")
        logger.info(f"预期路由: {test_case.expected_route}")
        logger.info(f"实际路由: {actual_route}")
        logger.info(f"路由逻辑: {actual_logic}")
        logger.info(f"预期节点: {test_case.expected_node}")
        if test_case.sub_decision:
            logger.info(f"预期子决策: {test_case.sub_decision}")
        logger.info(f"回复摘要: {response_text[:150]}...")
        logger.info(f"状态: {status}")
        logger.info(f"{'='*80}\n")

        return {
            "test_case": test_case.description,
            "question": test_case.question,
            "expected_route": test_case.expected_route,
            "actual_route": actual_route,
            "route_match": route_match,
            "logic": actual_logic,
            "response": response_text,
            "status": status,
        }

    except Exception as e:
        logger.error(f"测试失败: {test_case.description}")
        logger.exception(f"错误: {str(e)}")
        return {
            "test_case": test_case.description,
            "question": test_case.question,
            "expected_route": test_case.expected_route,
            "actual_route": "ERROR",
            "route_match": False,
            "error": str(e),
            "status": "ERROR",
        }


# ============================================================================
# 测试用例定义
# ============================================================================

TEST_CASES = [
    # 1. General-Query 测试
    RoutingTestCase(
        question="你好",
        expected_route="general-query",
        expected_node="respond_to_general_query",
        description="基本问候",
    ),
    RoutingTestCase(
        question="早上好",
        expected_route="general-query",
        expected_node="respond_to_general_query",
        description="礼貌寒暄",
    ),
    RoutingTestCase(
        question="谢谢你的帮助",
        expected_route="general-query",
        expected_node="respond_to_general_query",
        description="感谢反馈",
    ),
    RoutingTestCase(
        question="今天心情不错",
        expected_route="general-query",
        expected_node="respond_to_general_query",
        description="情绪表达",
    ),
    # 2. Additional-Query 测试
    RoutingTestCase(
        question="我想做菜",
        expected_route="additional-query",
        expected_node="get_additional_info",
        description="模糊提问（缺菜名）",
    ),
    RoutingTestCase(
        question="这个菜怎么做好吃",
        expected_route="additional-query",
        expected_node="get_additional_info",
        description="缺少关键信息（哪道菜）",
    ),
    RoutingTestCase(
        question="这个菜热量高吗",
        expected_route="additional-query",
        expected_node="get_additional_info",
        description="营养问题缺份量",
    ),
    RoutingTestCase(
        question="我做的菜不好吃",
        expected_route="additional-query",
        expected_node="get_additional_info",
        description="烹饪失败描述不清",
    ),
    # 3. KB-Query 测试（向量知识库）
    RoutingTestCase(
        question="宫保鸡丁的历史典故是什么",
        expected_route="kb-query",
        expected_node="create_kb_query",
        description="菜谱历史典故",
        sub_decision="KB Multi-tool: Milvus 或 pgvector",
    ),
    RoutingTestCase(
        question="佛跳墙这道菜的由来",
        expected_route="kb-query",
        expected_node="create_kb_query",
        description="菜品背景文化",
        sub_decision="KB Multi-tool: 智能选择向量检索源",
    ),
    RoutingTestCase(
        question="川菜的特点是什么",
        expected_route="kb-query",
        expected_node="create_kb_query",
        description="地域流派介绍",
        sub_decision="KB Multi-tool: 可能合并多个来源",
    ),
    RoutingTestCase(
        question="川菜大师有哪些",
        expected_route="kb-query",
        expected_node="create_kb_query",
        description="名厨偏好介绍",
    ),
    RoutingTestCase(
        question="西兰花有什么营养价值",
        expected_route="kb-query",
        expected_node="create_kb_query",
        description="食材营养科普",
        sub_decision="KB Multi-tool: Reranker 重排序",
    ),
    # 4. GraphRAG-Query 测试（图谱推理）
    RoutingTestCase(
        question="红烧肉怎么做",
        expected_route="graphrag-query",
        expected_node="create_research_plan",
        description="菜谱做法步骤 → LightRAG",
        sub_decision="共享 LightRAG 索引检索做法与实体关系",
    ),
    RoutingTestCase(
        question="宫保鸡丁需要哪些食材",
        expected_route="graphrag-query",
        expected_node="create_research_plan",
        description="食材用量查询 → LightRAG",
        sub_decision="共享 LightRAG 索引检索菜品与食材关系",
    ),
    RoutingTestCase(
        question="炒青菜怎么保持翠绿",
        expected_route="graphrag-query",
        expected_node="create_research_plan",
        description="烹饪技巧细节 → LightRAG",
        sub_decision="共享 LightRAG 检索资料与相关实体",
    ),
    RoutingTestCase(
        question="怎么判断鱼熟了",
        expected_route="graphrag-query",
        expected_node="create_research_plan",
        description="火候判断 → GraphRAG",
        sub_decision="共享 LightRAG 索引检索火候资料",
    ),
    RoutingTestCase(
        question="为什么我做的红烧肉发柴",
        expected_route="graphrag-query",
        expected_node="create_research_plan",
        description="失败排查 → LightRAG",
        sub_decision="对比正确做法推理原因",
    ),
    RoutingTestCase(
        question="什么菜适合感冒的人吃",
        expected_route="graphrag-query",
        expected_node="create_research_plan",
        description="综合知识检索 → LightRAG",
        sub_decision="共享 LightRAG 检索食材相关来源资料",
    ),
    # 5. Text2SQL-Query 测试（领域启用 SQL 且配置 SQL_DATABASE_URL 时适用）
    RoutingTestCase(
        question="数据库里有多少道菜",
        expected_route="text2sql-query",  # 启发式关键词 "多少"
        expected_node="create_research_plan",
        description="数据统计 → Text2SQL",
        sub_decision="text2sql_query: SELECT COUNT(*)",
    ),
    RoutingTestCase(
        question="哪个菜系的菜谱最多",
        expected_route="text2sql-query",  # 启发式关键词 "最多"
        expected_node="create_research_plan",
        description="数据排名 → Text2SQL",
        sub_decision="text2sql_query: GROUP BY + ORDER BY",
    ),
    RoutingTestCase(
        question="统计每个口味的菜谱数量",
        expected_route="text2sql-query",  # 启发式关键词 "统计"
        expected_node="create_research_plan",
        description="数据趋势分析 → Text2SQL",
        sub_decision="text2sql_query: GROUP BY 查询",
    ),
    # 6. Image-Query 测试
    RoutingTestCase(
        question="生成一张红烧肉的图片",
        expected_route="image-query",
        expected_node="create_image_query",
        description="图片生成",
        sub_decision="LLM 优化提示词 → CogView-4 API",
    ),
    # 7. Guardrails 边界测试
    RoutingTestCase(
        question="今天天气怎么样",
        expected_route="additional-query",  # 可能先进入 additional-query
        expected_node="get_additional_info",
        description="无关问题（应被 Guardrails 拦截）",
        sub_decision="Guardrails 返回 end → 礼貌拒绝",
    ),
    RoutingTestCase(
        question="我肚子疼应该吃什么药",
        expected_route="additional-query",
        expected_node="get_additional_info",
        description="医疗诊断（应被 Guardrails 拦截）",
        sub_decision="Guardrails 拦截 → 建议咨询医生",
    ),
]


async def run_test_suite():
    """运行完整测试套件"""

    logger.info("=" * 80)
    logger.info("开始 GustoBot Agent 路由测试")
    logger.info("=" * 80)

    results = []
    for i, test_case in enumerate(TEST_CASES, 1):
        logger.info(f"\n[{i}/{len(TEST_CASES)}] 测试: {test_case.description}")
        result = await test_routing(test_case, session_id=f"test_{i}")
        results.append(result)

        # 避免请求过快
        await asyncio.sleep(1)

    # 汇总统计
    total = len(results)
    passed = sum(1 for r in results if r.get("route_match", False))
    failed = total - passed

    logger.info("\n" + "=" * 80)
    logger.info("测试汇总")
    logger.info("=" * 80)
    logger.info(f"总计: {total}")
    logger.info(f"通过: {passed}")
    logger.info(f"失败: {failed}")
    logger.info(f"成功率: {passed/total*100:.1f}%")
    logger.info("=" * 80)

    # 输出失败详情
    if failed > 0:
        logger.info("\n失败的测试用例:")
        for r in results:
            if not r.get("route_match", False):
                logger.info(f"  {r['test_case']}")
                logger.info(f"     问题: {r['question']}")
                logger.info(f"     预期: {r['expected_route']}")
                logger.info(f"     实际: {r['actual_route']}")
                logger.info("")

    return results


async def run_single_test(question: str):
    """运行单个测试（快速调试用）"""
    test_case = RoutingTestCase(
        question=question,
        expected_route="unknown",
        expected_node="unknown",
        description="手动测试",
    )
    result = await test_routing(test_case)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GustoBot Agent 路由测试")
    parser.add_argument(
        "--single",
        type=str,
        help="运行单个测试问题（快速调试）",
    )
    parser.add_argument(
        "--suite",
        action="store_true",
        help="运行完整测试套件",
    )

    args = parser.parse_args()

    if args.single:
        # 单个测试模式
        asyncio.run(run_single_test(args.single))
    elif args.suite or not (args.single or args.suite):
        # 默认运行完整测试套件
        results = asyncio.run(run_test_suite())
        raise SystemExit(0 if all(result["route_match"] for result in results) else 1)
