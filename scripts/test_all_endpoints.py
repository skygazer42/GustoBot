#!/usr/bin/env python3
"""
Full-stack API probe for GustoBot.

Runs a best-effort integration check against every operation exposed in:
  - Backend OpenAPI (default: http://localhost:8000)
  - KB ingest OpenAPI (default: http://localhost:8100)

Notes:
  - Some endpoints may call external LLM/embedding/image providers depending on your `.env`.
  - Destructive endpoints are NOT executed by default.
"""


import argparse
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Set, Tuple

import httpx


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def _print_result(result: CheckResult) -> None:
    status = "OK" if result.ok else "FAIL"
    suffix = f" - {result.detail}" if result.detail else ""
    print(f"[{status}] {result.name}{suffix}")


def _openapi_operations(client: httpx.Client, base_url: str) -> Set[Tuple[str, str]]:
    resp = client.get(f"{base_url.rstrip('/')}/openapi.json")
    resp.raise_for_status()
    spec = resp.json()

    operations: Set[Tuple[str, str]] = set()
    for path, methods in spec["paths"].items():
        if not isinstance(methods, dict):
            continue
        for method in methods.keys():
            if str(method).lower() in HTTP_METHODS:
                operations.add((str(method).upper(), str(path)))
    return operations


def _iter_sse_data_lines(response: httpx.Response) -> Iterable[str]:
    for raw in response.iter_lines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("data:"):
            yield line[len("data:") :].strip()


def _expect_json(resp: httpx.Response) -> Any:
    resp.raise_for_status()
    if not resp.content:
        return None
    return resp.json()


def _one_px_png_bytes() -> bytes:
    # 1x1 transparent PNG
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_backend(*, base_url: str, include_destructive: bool) -> List[CheckResult]:
    timeout = httpx.Timeout(180.0)
    results: List[CheckResult] = []

    tested_ops: Set[Tuple[str, str]] = set()

    def record(method: str, path_template: str) -> None:
        tested_ops.add((method.upper(), path_template))

    def ok(name: str, detail: str = "") -> None:
        results.append(CheckResult(name, True, detail))

    def fail(name: str, detail: str) -> None:
        results.append(CheckResult(name, False, detail))

    with httpx.Client(timeout=timeout, trust_env=False) as client:
        # OpenAPI discovery (coverage target)
        try:
            openapi_ops = _openapi_operations(client, base_url)
            ok("backend openapi", f"ops={len(openapi_ops)}")
        except Exception as exc:
            return [CheckResult("backend openapi", False, str(exc))]

        # Basic endpoints -----------------------------------------------------
        try:
            resp = client.get(f"{base_url}/health")
            record("GET", "/health")
            data = _expect_json(resp)
            if isinstance(data, dict) and data.get("status") == "healthy":
                ok("GET /health")
            else:
                fail("GET /health", f"unexpected payload: {data!r}")
        except Exception as exc:
            fail("GET /health", str(exc))

        try:
            resp = client.get(f"{base_url}/api")
            record("GET", "/api")
            data = _expect_json(resp)
            ok("GET /api", f"version={data.get('version')}" if isinstance(data, dict) else "")
        except Exception as exc:
            fail("GET /api", str(exc))

        try:
            resp = client.get(f"{base_url}/", follow_redirects=False)
            record("GET", "/")
            if resp.status_code in {302, 303, 307, 308} and resp.headers.get("location") == "/docs":
                ok("GET / (redirect)")
            elif resp.status_code == 200:
                ok("GET /")
            else:
                fail(
                    "GET /", f"status={resp.status_code} location={resp.headers.get('location')!r}"
                )
        except Exception as exc:
            fail("GET /", str(exc))

        try:
            resp = client.get(f"{base_url}/favicon.ico")
            record("GET", "/favicon.ico")
            if resp.status_code == 200:
                ok("GET /favicon.ico")
            else:
                fail("GET /favicon.ico", f"status={resp.status_code}")
        except Exception as exc:
            fail("GET /favicon.ico", str(exc))

        # Chat endpoints ------------------------------------------------------
        try:
            resp = client.get(f"{base_url}/api/v1/chat/routes")
            record("GET", "/api/v1/chat/routes")
            _expect_json(resp)
            ok("GET /api/v1/chat/routes")
        except Exception as exc:
            fail("GET /api/v1/chat/routes", str(exc))

        chat_session_id = str(uuid.uuid4())
        try:
            resp = client.post(
                f"{base_url}/api/v1/chat/",
                json={"message": "你好", "session_id": chat_session_id, "stream": False},
                headers={"Content-Type": "application/json"},
            )
            record("POST", "/api/v1/chat/")
            data = _expect_json(resp)
            if isinstance(data, dict) and data.get("session_id"):
                chat_session_id = str(data["session_id"])
                ok("POST /api/v1/chat/", f"route={data.get('route')}")
            else:
                fail("POST /api/v1/chat/", f"unexpected payload: {data!r}")
        except Exception as exc:
            fail("POST /api/v1/chat/", str(exc))

        try:
            resp = client.get(f"{base_url}/api/v1/chat/history/{chat_session_id}")
            record("GET", "/api/v1/chat/history/{session_id}")
            data = _expect_json(resp)
            if isinstance(data, list) and len(data) >= 2:
                ok("GET /api/v1/chat/history/{session_id}", f"count={len(data)}")
            else:
                fail("GET /api/v1/chat/history/{session_id}", f"unexpected payload: {data!r}")
        except Exception as exc:
            fail("GET /api/v1/chat/history/{session_id}", str(exc))

        try:
            payload = {"message": "你好", "session_id": str(uuid.uuid4()), "stream": True}
            with client.stream(
                "POST",
                f"{base_url}/api/v1/chat/stream",
                json=payload,
                headers={"Accept": "text/event-stream", "Content-Type": "application/json"},
            ) as resp:
                record("POST", "/api/v1/chat/stream")
                resp.raise_for_status()
                done = False
                seen = 0
                for data_line in _iter_sse_data_lines(resp):
                    seen += 1
                    try:
                        chunk = json.loads(data_line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, dict) and chunk.get("type") == "done":
                        done = True
                        break
                    if seen > 800:
                        break
                if done:
                    ok("POST /api/v1/chat/stream", "done=true")
                else:
                    fail("POST /api/v1/chat/stream", f"no done chunk (seen={seen})")
        except Exception as exc:
            fail("POST /api/v1/chat/stream", str(exc))

        try:
            resp = client.delete(f"{base_url}/api/v1/chat/session/{chat_session_id}")
            record("DELETE", "/api/v1/chat/session/{session_id}")
            _expect_json(resp)
            ok("DELETE /api/v1/chat/session/{session_id}")
        except Exception as exc:
            fail("DELETE /api/v1/chat/session/{session_id}", str(exc))

        # Sessions endpoints --------------------------------------------------
        user_id = f"probe_user_{uuid.uuid4().hex[:8]}"
        sessions_id = str(uuid.uuid4())

        try:
            resp = client.get(f"{base_url}/api/v1/sessions/")
            record("GET", "/api/v1/sessions/")
            data = _expect_json(resp)
            ok("GET /api/v1/sessions/", f"count={len(data) if isinstance(data, list) else 'n/a'}")
        except Exception as exc:
            fail("GET /api/v1/sessions/", str(exc))

        try:
            resp = client.post(
                f"{base_url}/api/v1/sessions/",
                json={"id": sessions_id, "title": "Probe Session", "user_id": user_id},
            )
            record("POST", "/api/v1/sessions/")
            data = _expect_json(resp)
            ok("POST /api/v1/sessions/", f"id={data.get('id')}" if isinstance(data, dict) else "")
        except Exception as exc:
            fail("POST /api/v1/sessions/", str(exc))

        try:
            resp = client.get(f"{base_url}/api/v1/sessions/{sessions_id}")
            record("GET", "/api/v1/sessions/{session_id}")
            _expect_json(resp)
            ok("GET /api/v1/sessions/{session_id}")
        except Exception as exc:
            fail("GET /api/v1/sessions/{session_id}", str(exc))

        try:
            resp = client.patch(
                f"{base_url}/api/v1/sessions/{sessions_id}",
                json={"title": "Probe Session (Updated)"},
            )
            record("PATCH", "/api/v1/sessions/{session_id}")
            data = _expect_json(resp)
            ok(
                "PATCH /api/v1/sessions/{session_id}",
                f"title={data.get('title')}" if isinstance(data, dict) else "",
            )
        except Exception as exc:
            fail("PATCH /api/v1/sessions/{session_id}", str(exc))

        try:
            resp = client.get(f"{base_url}/api/v1/sessions/user/{user_id}/count")
            record("GET", "/api/v1/sessions/user/{user_id}/count")
            _expect_json(resp)
            ok("GET /api/v1/sessions/user/{user_id}/count")
        except Exception as exc:
            fail("GET /api/v1/sessions/user/{user_id}/count", str(exc))

        try:
            resp = client.post(
                f"{base_url}/api/v1/sessions/{sessions_id}/messages",
                json={
                    "session_id": sessions_id,
                    "message_type": "user_query",
                    "content": "Probe message",
                    "message_metadata": {"source": "scripts/test_all_endpoints.py"},
                    "order_index": 1,
                },
            )
            record("POST", "/api/v1/sessions/{session_id}/messages")
            _expect_json(resp)
            ok("POST /api/v1/sessions/{session_id}/messages")
        except Exception as exc:
            fail("POST /api/v1/sessions/{session_id}/messages", str(exc))

        try:
            resp = client.post(
                f"{base_url}/api/v1/sessions/{sessions_id}/snapshot",
                json={
                    "session_id": sessions_id,
                    "query": "probe snapshot query",
                    "response_data": {"ok": True},
                },
            )
            record("POST", "/api/v1/sessions/{session_id}/snapshot")
            _expect_json(resp)
            ok("POST /api/v1/sessions/{session_id}/snapshot")
        except Exception as exc:
            fail("POST /api/v1/sessions/{session_id}/snapshot", str(exc))

        try:
            resp = client.delete(f"{base_url}/api/v1/sessions/{sessions_id}")
            record("DELETE", "/api/v1/sessions/{session_id}")
            if resp.status_code == 204:
                ok("DELETE /api/v1/sessions/{session_id}")
            else:
                fail(
                    "DELETE /api/v1/sessions/{session_id}",
                    f"status={resp.status_code} body={resp.text[:120]!r}",
                )
        except Exception as exc:
            fail("DELETE /api/v1/sessions/{session_id}", str(exc))

        # Upload endpoints ----------------------------------------------------
        uploaded_file_id: Optional[str] = None
        uploaded_file_name: Optional[str] = None
        try:
            resp = client.post(
                f"{base_url}/api/v1/upload/file",
                files={"file": ("probe.txt", b"hello from api probe\n", "text/plain")},
            )
            record("POST", "/api/v1/upload/file")
            data = _expect_json(resp)
            uploaded_file_id = data.get("file_id") if isinstance(data, dict) else None
            uploaded_file_name = data.get("filename") if isinstance(data, dict) else None
            ok("POST /api/v1/upload/file", f"file_id={uploaded_file_id}")
        except Exception as exc:
            fail("POST /api/v1/upload/file", str(exc))

        if uploaded_file_name:
            try:
                resp = client.get(f"{base_url}/api/v1/upload/files/{uploaded_file_name}")
                record("GET", "/api/v1/upload/files/{filename}")
                if resp.status_code == 200 and b"hello from api probe" in resp.content:
                    ok("GET /api/v1/upload/files/{filename}")
                else:
                    fail("GET /api/v1/upload/files/{filename}", f"status={resp.status_code}")
            except Exception as exc:
                fail("GET /api/v1/upload/files/{filename}", str(exc))

        uploaded_image_name: Optional[str] = None
        try:
            resp = client.post(
                f"{base_url}/api/v1/upload/image",
                files={"image": ("probe.png", _one_px_png_bytes(), "image/png")},
            )
            record("POST", "/api/v1/upload/image")
            data = _expect_json(resp)
            uploaded_image_name = data.get("filename") if isinstance(data, dict) else None
            ok("POST /api/v1/upload/image")
        except Exception as exc:
            fail("POST /api/v1/upload/image", str(exc))

        if uploaded_image_name:
            try:
                resp = client.get(f"{base_url}/api/v1/upload/images/{uploaded_image_name}")
                record("GET", "/api/v1/upload/images/{filename}")
                if resp.status_code == 200 and resp.content.startswith(b"\x89PNG"):
                    ok("GET /api/v1/upload/images/{filename}")
                else:
                    fail("GET /api/v1/upload/images/{filename}", f"status={resp.status_code}")
            except Exception as exc:
                fail("GET /api/v1/upload/images/{filename}", str(exc))

        if uploaded_file_id:
            try:
                resp = client.delete(f"{base_url}/api/v1/upload/{uploaded_file_id}")
                record("DELETE", "/api/v1/upload/{file_id}")
                _expect_json(resp)
                ok("DELETE /api/v1/upload/{file_id}")
            except Exception as exc:
                fail("DELETE /api/v1/upload/{file_id}", str(exc))

        if ("GET", "/api/v1/knowledge/stats") in openapi_ops:
            # Knowledge endpoints -------------------------------------------------
            try:
                resp = client.get(f"{base_url}/api/v1/knowledge/stats")
                record("GET", "/api/v1/knowledge/stats")
                _expect_json(resp)
                ok("GET /api/v1/knowledge/stats")
            except Exception as exc:
                fail("GET /api/v1/knowledge/stats", str(exc))

            try:
                resp = client.post(
                    f"{base_url}/api/v1/knowledge/search", json={"query": "红烧肉", "top_k": 2}
                )
                record("POST", "/api/v1/knowledge/search")
                data = _expect_json(resp)
                ok(
                    "POST /api/v1/knowledge/search",
                    f"count={data.get('count')}" if isinstance(data, dict) else "",
                )
            except Exception as exc:
                fail("POST /api/v1/knowledge/search", str(exc))

            added_recipe_base_id: Optional[str] = None
            try:
                recipe_id = f"recipe_{uuid.uuid4().hex[:8]}"
                resp = client.post(
                    f"{base_url}/api/v1/knowledge/recipes",
                    json={
                        "id": recipe_id,
                        "name": "探针测试菜",
                        "category": "probe",
                        "time": "1分钟",
                        "ingredients": ["水"],
                        "steps": ["加热"],
                        "tips": "probe",
                    },
                )
                record("POST", "/api/v1/knowledge/recipes")
                data = _expect_json(resp)
                added_recipe_base_id = (
                    data.get("recipe_id") if isinstance(data, dict) else recipe_id
                )
                ok("POST /api/v1/knowledge/recipes", f"recipe_id={added_recipe_base_id}")
            except Exception as exc:
                fail("POST /api/v1/knowledge/recipes", str(exc))

            try:
                resp = client.post(
                    f"{base_url}/api/v1/knowledge/recipes/batch",
                    json=[
                        {
                            "name": "批量菜A",
                            "category": "probe",
                            "ingredients": ["水"],
                            "steps": ["加热"],
                        },
                        {
                            "name": "批量菜B",
                            "category": "probe",
                            "ingredients": ["水"],
                            "steps": ["加热"],
                        },
                    ],
                )
                record("POST", "/api/v1/knowledge/recipes/batch")
                data = _expect_json(resp)
                ok(
                    "POST /api/v1/knowledge/recipes/batch",
                    f"{data.get('statistics')}" if isinstance(data, dict) else "",
                )
            except Exception as exc:
                fail("POST /api/v1/knowledge/recipes/batch", str(exc))

            if added_recipe_base_id:
                try:
                    chunk_id = f"{added_recipe_base_id}_0"
                    resp = client.delete(f"{base_url}/api/v1/knowledge/recipes/{chunk_id}")
                    record("DELETE", "/api/v1/knowledge/recipes/{recipe_id}")
                    _expect_json(resp)
                    ok("DELETE /api/v1/knowledge/recipes/{recipe_id}", f"deleted={chunk_id}")
                except Exception as exc:
                    fail("DELETE /api/v1/knowledge/recipes/{recipe_id}", str(exc))

            try:
                resp = client.delete(f"{base_url}/api/v1/knowledge/clear")
                record("DELETE", "/api/v1/knowledge/clear")
                if include_destructive:
                    resp2 = client.delete(f"{base_url}/api/v1/knowledge/clear?confirm=true")
                    resp2.raise_for_status()
                    ok("DELETE /api/v1/knowledge/clear", "cleared")
                elif resp.status_code == 400:
                    ok("DELETE /api/v1/knowledge/clear", "confirm required")
                else:
                    fail("DELETE /api/v1/knowledge/clear", f"expected 400, got {resp.status_code}")
            except Exception as exc:
                fail("DELETE /api/v1/knowledge/clear", str(exc))

        # Domain knowledge: validate the shared query and input boundaries.
        try:
            resp = client.get(f"{base_url}/api/v1/ontology/domain")
            record("GET", "/api/v1/ontology/domain")
            data = _expect_json(resp)
            ok("GET /api/v1/ontology/domain", f"domain={data['id']}")
        except Exception as exc:
            fail("GET /api/v1/ontology/domain", str(exc))

        empty_graph: dict[str, Any] = {"entities": [], "relations": [], "sources": []}
        for path, ontology_payload, expected_status in (
            ("/api/v1/ontology/validate", empty_graph, 200),
            ("/api/v1/ontology/facts", empty_graph, 422),
            ("/api/v1/ontology/extract", {"sources": []}, 422),
        ):
            try:
                resp = client.post(f"{base_url}{path}", json=ontology_payload)
                record("POST", path)
                if resp.status_code == expected_status:
                    ok(f"POST {path}", f"status={expected_status}; no index writes")
                else:
                    fail(f"POST {path}", f"expected {expected_status}, got {resp.status_code}")
            except Exception as exc:
                fail(f"POST {path}", str(exc))

        try:
            resp = client.post(
                f"{base_url}/api/v1/ontology/query",
                json={"question": "当前资料有哪些相关实体和关系？", "mode": "hybrid", "top_k": 3},
            )
            record("POST", "/api/v1/ontology/query")
            _expect_json(resp)
            ok("POST /api/v1/ontology/query")
        except Exception as exc:
            fail("POST /api/v1/ontology/query", str(exc))

        # LightRAG endpoints --------------------------------------------------
        try:
            resp = client.get(f"{base_url}/api/v1/lightrag/stats")
            record("GET", "/api/v1/lightrag/stats")
            _expect_json(resp)
            ok("GET /api/v1/lightrag/stats")
        except Exception as exc:
            fail("GET /api/v1/lightrag/stats", str(exc))

        try:
            resp = client.post(
                f"{base_url}/api/v1/lightrag/query",
                json={"query": "红烧肉怎么做？", "mode": "hybrid", "top_k": 3, "stream": False},
            )
            record("POST", "/api/v1/lightrag/query")
            _expect_json(resp)
            ok("POST /api/v1/lightrag/query")
        except Exception as exc:
            fail("POST /api/v1/lightrag/query", str(exc))

        try:
            with client.stream(
                "POST",
                f"{base_url}/api/v1/lightrag/query-stream",
                json={"query": "红烧肉怎么做？", "mode": "hybrid", "top_k": 3},
                headers={"Accept": "text/event-stream", "Content-Type": "application/json"},
            ) as resp:
                record("POST", "/api/v1/lightrag/query-stream")
                resp.raise_for_status()
                done = False
                seen = 0
                for data_line in _iter_sse_data_lines(resp):
                    seen += 1
                    if data_line == "[DONE]":
                        done = True
                        break
                    if seen > 800:
                        break
                if done:
                    ok("POST /api/v1/lightrag/query-stream", "done=true")
                else:
                    fail("POST /api/v1/lightrag/query-stream", f"no [DONE] (seen={seen})")
        except Exception as exc:
            fail("POST /api/v1/lightrag/query-stream", str(exc))

        try:
            resp = client.post(
                f"{base_url}/api/v1/lightrag/insert",
                json={"documents": ["探针文档：红烧肉是一道经典菜。"]},
            )
            record("POST", "/api/v1/lightrag/insert")
            _expect_json(resp)
            ok("POST /api/v1/lightrag/insert")
        except Exception as exc:
            fail("POST /api/v1/lightrag/insert", str(exc))

        try:
            resp = client.post(
                f"{base_url}/api/v1/lightrag/test-modes", params={"query": "红烧肉怎么做？"}
            )
            record("POST", "/api/v1/lightrag/test-modes")
            _expect_json(resp)
            ok("POST /api/v1/lightrag/test-modes")
        except Exception as exc:
            fail("POST /api/v1/lightrag/test-modes", str(exc))

        # Coverage check ------------------------------------------------------
        missing = sorted(openapi_ops - tested_ops)
        if missing:
            fail(
                "backend openapi coverage",
                f"missing {len(missing)} ops, e.g. {missing[:8]}",
            )
        else:
            ok("backend openapi coverage", f"{len(tested_ops)}/{len(openapi_ops)}")

        # Extra (not in OpenAPI): legacy alias route
        try:
            resp = client.post(
                f"{base_url}/api/v1/chat/chat",
                json={"message": "你好", "session_id": str(uuid.uuid4()), "stream": False},
            )
            resp.raise_for_status()
            ok("POST /api/v1/chat/chat (legacy)")
        except Exception as exc:
            fail("POST /api/v1/chat/chat (legacy)", str(exc))

    return results


def test_ingest_service(*, base_url: str) -> List[CheckResult]:
    timeout = httpx.Timeout(120.0)
    results: List[CheckResult] = []

    tested_ops: Set[Tuple[str, str]] = set()

    def record(method: str, path_template: str) -> None:
        tested_ops.add((method.upper(), path_template))

    def ok(name: str, detail: str = "") -> None:
        results.append(CheckResult(name, True, detail))

    def fail(name: str, detail: str) -> None:
        results.append(CheckResult(name, False, detail))

    with httpx.Client(timeout=timeout, trust_env=False) as client:
        try:
            openapi_ops = _openapi_operations(client, base_url)
            ok("ingest openapi", f"ops={len(openapi_ops)}")
        except Exception as exc:
            return [CheckResult("ingest openapi", False, str(exc))]

        try:
            resp = client.get(f"{base_url}/health")
            record("GET", "/health")
            data = _expect_json(resp)
            if isinstance(data, dict) and data.get("status") == "ok":
                ok("ingest GET /health")
            else:
                fail("ingest GET /health", f"unexpected payload: {data!r}")
        except Exception as exc:
            fail("ingest GET /health", str(exc))

        # Search endpoints exist in both /api and /api/v1/knowledge prefixes
        for prefix in ["/api", "/api/v1/knowledge"]:
            try:
                resp = client.post(
                    f"{base_url}{prefix}/search", json={"query": "宫保鸡丁", "top_k": 3}
                )
                record("POST", f"{prefix}/search")
                if resp.status_code == 200:
                    data = _expect_json(resp)
                    ok(
                        f"ingest POST {prefix}/search",
                        f"count={data.get('count')}" if isinstance(data, dict) else "",
                    )
                elif resp.status_code in {401, 403, 502, 503}:
                    detail = ""
                    try:
                        payload = resp.json()
                        if isinstance(payload, dict) and payload.get("detail"):
                            detail = str(payload.get("detail"))
                    except json.JSONDecodeError:
                        pass
                    ok(
                        f"ingest POST {prefix}/search",
                        f"unavailable ({resp.status_code}) {detail}"[:120],
                    )
                else:
                    fail(
                        f"ingest POST {prefix}/search",
                        f"status={resp.status_code} body={resp.text[:120]!r}",
                    )
            except Exception as exc:
                fail(f"ingest POST {prefix}/search", str(exc))

            try:
                resp = client.post(
                    f"{base_url}{prefix}/search/hybrid",
                    json={"query": "宫保鸡丁", "vector_top_k": 3, "rerank_top_k": 2},
                )
                record("POST", f"{prefix}/search/hybrid")
                if resp.status_code == 200:
                    _expect_json(resp)
                    ok(f"ingest POST {prefix}/search/hybrid")
                elif resp.status_code in {401, 403, 502, 503}:
                    detail = ""
                    try:
                        payload = resp.json()
                        if isinstance(payload, dict) and payload.get("detail"):
                            detail = str(payload.get("detail"))
                    except json.JSONDecodeError:
                        pass
                    ok(
                        f"ingest POST {prefix}/search/hybrid",
                        f"unavailable ({resp.status_code}) {detail}"[:120],
                    )
                else:
                    fail(
                        f"ingest POST {prefix}/search/hybrid",
                        f"status={resp.status_code} body={resp.text[:120]!r}",
                    )
            except Exception as exc:
                fail(f"ingest POST {prefix}/search/hybrid", str(exc))

            # Excel (path) variant: use non-existent file and expect 404 (safe).
            try:
                resp = client.post(
                    f"{base_url}{prefix}/ingest/excel",
                    json={
                        "excel_path": "/no/such/file.xlsx",
                        "incremental": True,
                        "regenerate": False,
                    },
                )
                record("POST", f"{prefix}/ingest/excel")
                if resp.status_code == 404:
                    ok(f"ingest POST {prefix}/ingest/excel", "404 expected")
                else:
                    fail(
                        f"ingest POST {prefix}/ingest/excel",
                        f"expected 404, got {resp.status_code}",
                    )
            except Exception as exc:
                fail(f"ingest POST {prefix}/ingest/excel", str(exc))

            # Excel upload variant: non-excel extension should return 400 before background work.
            try:
                resp = client.post(
                    f"{base_url}{prefix}/ingest/excel/upload",
                    files={"file": ("not_excel.txt", b"nope", "text/plain")},
                    data={"incremental": "false"},
                )
                record("POST", f"{prefix}/ingest/excel/upload")
                if resp.status_code == 400:
                    ok(f"ingest POST {prefix}/ingest/excel/upload", "400 expected")
                else:
                    fail(
                        f"ingest POST {prefix}/ingest/excel/upload",
                        f"expected 400, got {resp.status_code} ({resp.text[:120]!r})",
                    )
            except Exception as exc:
                fail(f"ingest POST {prefix}/ingest/excel/upload", str(exc))

            # MySQL ingest: queue background job (cheap, limit=1, mode=flatten).
            try:
                resp = client.post(
                    f"{base_url}{prefix}/ingest/mysql",
                    json={
                        "connection_url": (
                            "mysql+pymysql://recipe_user:recipepass@mysql:3306/recipe_db"
                        ),
                        "table": "recipes",
                        "extra_metadata": {"source": "probe"},
                        "mode": "flatten",
                        "limit": 1,
                    },
                )
                record("POST", f"{prefix}/ingest/mysql")
                if resp.status_code == 202:
                    ok(f"ingest POST {prefix}/ingest/mysql", "queued")
                else:
                    fail(
                        f"ingest POST {prefix}/ingest/mysql",
                        f"status={resp.status_code} body={resp.text[:120]!r}",
                    )
            except Exception as exc:
                fail(f"ingest POST {prefix}/ingest/mysql", str(exc))

        missing = sorted(openapi_ops - tested_ops)
        if missing:
            fail("ingest openapi coverage", f"missing {len(missing)} ops, e.g. {missing[:8]}")
        else:
            ok("ingest openapi coverage", f"{len(tested_ops)}/{len(openapi_ops)}")

    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe all API endpoints (integration)")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--ingest-url", default="http://localhost:8100", help="KB ingest base URL")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip kb_ingest API tests")
    parser.add_argument(
        "--include-destructive",
        action="store_true",
        help="Execute destructive endpoints (e.g. clear vector store). Use with care.",
    )
    args = parser.parse_args(argv)

    started = time.time()
    all_results: List[CheckResult] = []

    print(f"== Backend API probe: {args.base_url} ==")
    backend_results = test_backend(
        base_url=args.base_url.rstrip("/"),
        include_destructive=args.include_destructive,
    )
    all_results.extend(backend_results)
    for r in backend_results:
        _print_result(r)

    if not args.skip_ingest:
        print(f"\n== KB ingest API probe: {args.ingest_url} ==")
        ingest_results = test_ingest_service(base_url=args.ingest_url.rstrip("/"))
        all_results.extend(ingest_results)
        for r in ingest_results:
            _print_result(r)

    failed = [r for r in all_results if not r.ok]
    elapsed = time.time() - started
    print("\n== Summary ==")
    print(f"Total: {len(all_results)} checks | Failed: {len(failed)} | Time: {elapsed:.1f}s")
    if failed:
        print("Failed checks:")
        for r in failed:
            print(f"- {r.name}: {r.detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
