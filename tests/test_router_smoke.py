#!/usr/bin/env python3
"""
简易路由冒烟测试

运行方式:
    python tests/test_router_smoke.py

依赖:
    - 后端服务已在本地或容器内运行，默认地址 http://localhost:8000
    - 可通过环境变量 GUSTOBOT_BASE_URL 自定义地址
"""

import asyncio
import os
import sys
from typing import Any

import httpx

BASE_URL = os.getenv("GUSTOBOT_BASE_URL", "http://localhost:8000").rstrip("/")
CHAT_ENDPOINT = f"{BASE_URL}/api/v1/chat/"

# 定义测试用例
TEST_CASES: list[dict[str, Any]] = [
    {
        "question": "你好",
        "expected_route": "general-query",
        "description": "闲聊路由应走 general-query",
    },
    {
        "question": "我想做菜",
        "expected_route": "knowledge-query",
        "description": "统一知识问答负责澄清缺少的信息",
    },
    {
        "question": "宫保鸡丁的历史典故是什么",
        "expected_route": "knowledge-query",
        "description": "知识库查询（允许无命中时 sources 为空）",
    },
    {
        "question": "小炒肉需要哪些食材？",
        "expected_route": "knowledge-query",
        "description": "统一知识问答查询食材，答案以现有记录为准",
    },
    {
        "question": "数据库里有多少道菜",
        "expected_route": "knowledge-query",
        "description": "统一知识问答处理统计范围",
    },
    {
        "question": "生成一张红烧肉的图片",
        "expected_route": "image-generation",
        "action": "generate_image",
        "description": "图片生成由显式动作触发",
    },
]


async def invoke_chat(
    client: httpx.AsyncClient, message: str, idx: int, *, action: str = "knowledge"
) -> dict[str, Any]:
    """调用后端 Chat 接口。"""
    from gustobot.interfaces.http.v1.chat import ChatResponse

    payload = {
        "message": message,
        "session_id": f"router_smoke_{idx}",
        "stream": False,
        "action": action,
    }
    try:
        resp = await client.post(
            CHAT_ENDPOINT, json=payload, headers={"Content-Type": "application/json"}
        )
    except httpx.TimeoutException as exc:
        return {"status": 0, "payload": payload, "error": f"timeout: {exc}"}
    except httpx.HTTPError as exc:
        return {"status": 0, "payload": payload, "error": f"http_error: {exc}"}

    result: dict[str, Any] = {"status": resp.status_code, "payload": payload}
    if resp.status_code != 200:
        result["error"] = resp.text
        return result

    try:
        result["data"] = ChatResponse.model_validate_json(resp.content).model_dump(mode="json")
    except ValueError as exc:
        result["error"] = f"JSON decode failed: {exc}"
    return result


def evaluate_case(case: dict[str, Any], resp: dict[str, Any]) -> dict[str, Any]:
    """根据预期路由校验结果。"""
    outcome: dict[str, Any] = {
        "question": case["question"],
        "expected_route": case["expected_route"],
        "description": case["description"],
        "passed": False,
        "details": "",
    }

    if resp.get("status") != 200 or "data" not in resp:
        outcome["details"] = f"HTTP {resp.get('status')} - {resp.get('error', 'unknown error')}"
        return outcome

    data = resp["data"]
    actual_route = data["route"]
    outcome["actual_route"] = actual_route

    if actual_route != case["expected_route"]:
        outcome["details"] = f"路由不匹配 (actual={actual_route})"
        return outcome

    # 可选校验：是否返回来源
    if case.get("expect_sources"):
        sources = data["sources"]
        if not sources:
            outcome["details"] = "无来源返回，但预期应包含知识库来源"
            return outcome

    # 可选校验：回答中包含特定片段
    must_contain = case.get("must_contain")
    if must_contain:
        message = data["message"].strip()
        if must_contain not in message:
            outcome["details"] = f"回答未包含预期片段: {must_contain!r}"
            return outcome

    outcome["passed"] = True
    return outcome


def summarize(results: list[dict[str, Any]]) -> None:
    """输出汇总结果。"""
    total = len(results)
    passed = sum(1 for item in results if item["passed"])
    print("路由冒烟测试结果")
    for item in results:
        status = "通过" if item["passed"] else "失败"
        print(f"{status} {item['question']}")
        print(
            f"   预期路由: {item['expected_route']} | 实际路由: {item.get('actual_route', 'N/A')}"
        )
        if item["description"]:
            print(f"   描述: {item['description']}")
        if not item["passed"] and item["details"]:
            print(f"   失败原因: {item['details']}")
    print(f"通过率: {passed}/{total} = {passed / total * 100:.1f}%")


async def main() -> int:
    print("GustoBot 路由冒烟测试")
    print(f"目标接口: {CHAT_ENDPOINT}\n")

    # Run sequentially to avoid overloading external LLM/image services.
    # Keep a generous timeout so slow models still pass.
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        responses = []
        for idx, case in enumerate(TEST_CASES):
            responses.append(
                await invoke_chat(
                    client, case["question"], idx, action=case.get("action", "knowledge")
                )
            )

    results = [evaluate_case(case, resp) for case, resp in zip(TEST_CASES, responses)]
    summarize(results)
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:  # pragma: no cover - 手动中断
        exit_code = 130
    sys.exit(exit_code)
