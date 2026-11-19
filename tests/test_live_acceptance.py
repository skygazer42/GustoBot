"""Opt-in acceptance against a running server, real providers and actual stores.

Run with GUSTOBOT_RUN_LIVE_TESTS=1; the server owns its private model settings.
All created data is identified as acceptance material. No mocks are used.
"""

import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("GUSTOBOT_RUN_LIVE_TESTS") != "1",
    reason="Live acceptance requires an explicitly started backend and real model calls",
)
BASE_URL = os.environ.get("GUSTOBOT_LIVE_BASE_URL", "http://127.0.0.1:8000")
EVIDENCE = Path(__file__).resolve().parents[1] / ".superpowers/sdd/live-acceptance"


@pytest.fixture(scope="module")
def api():
    records = []

    def observe(response):
        records.append(
            {
                "method": response.request.method,
                "path": response.request.url.path,
                "status": response.status_code,
            }
        )

    with httpx.Client(
        base_url=BASE_URL, timeout=120, trust_env=False, event_hooks={"response": [observe]}
    ) as client:
        try:
            yield client
        finally:
            EVIDENCE.mkdir(parents=True, exist_ok=True)
            (EVIDENCE / "api-operations.json").write_text(
                json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )


@pytest.fixture(scope="module")
def recipes(api):
    token = uuid4().hex[:8]
    name = "联调佛跳墙" + token
    rows = [
        {
            "name": name,
            "record": {
                "主料": [["鸡肉", "100g"]],
                "辅料": [["白糖", amount]],
                "耗时": duration,
                "做法": ["准备食材", "加糖炖煮"],
                "source_uri": "acceptance://recipes/" + token + "/" + str(index),
            },
        }
        for index, (amount, duration) in enumerate((("10g", "半小时"), ("20g", "一小时")))
    ]
    unknown = {
        "name": "联调未知用量" + token,
        "record": {
            "辅料": [["白糖", "适量"]],
            "做法": ["按来源加入适量白糖"],
            "source_uri": "acceptance://recipes/" + token + "/unknown",
        },
    }
    response = api.post("/api/v1/knowledge/recipes/batch", json=[*rows, unknown])
    assert response.status_code == 201, response.text
    receipts = response.json()
    assert all(row["status"] == "graph_ready" for row in receipts)
    (EVIDENCE / "acceptance-recipes.json").write_text(
        json.dumps(
            {"name": name, "unknown": unknown["name"], "rows": rows, "receipts": receipts},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"name": name, "rows": rows, "receipts": receipts, "unknown": unknown["name"]}


def test_health_openapi_and_retired_routes(api):
    assert api.get("/").status_code == 307
    for path in ("/health", "/api", "/docs", "/openapi.json", "/favicon.ico"):
        assert api.get(path).status_code == 200
    spec = api.get("/openapi.json").json()
    assert "/api/v1/ontology/extract" in spec["paths"]
    assert not any("lightrag" in path for path in spec["paths"])
    assert api.get("/api/v1/lightrag/stats").status_code == 404
    assert api.post("/api/v1/chat/", json={"message": ""}).status_code == 422
    assert api.get("/api/v1/sessions/", params={"limit": 0}).status_code == 422
    assert api.get("/api/v1/chat/history/not-a-session").status_code == 404
    domain = api.get("/api/v1/ontology/domain")
    assert domain.status_code == 200 and domain.json()["id"] == "recipes"
    routes = api.get("/api/v1/chat/routes")
    assert routes.status_code == 200 and "knowledge" in json.dumps(routes.json())


def test_graph_idempotence_source_versions_and_exact_quantity(api, recipes):
    response = api.post(
        "/api/v1/ontology/query",
        json={
            "entity_type": "RecipeVariant",
            "anchor_names": [recipes["name"]],
            "operation": "count",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    assert api.post("/api/v1/knowledge/recipes", json=recipes["rows"][0]).status_code == 201
    repeated = api.post(
        "/api/v1/ontology/query",
        json={
            "entity_type": "RecipeVariant",
            "anchor_names": [recipes["name"]],
            "operation": "count",
        },
    )
    assert repeated.json()["total"] == 2
    numeric = api.post(
        "/api/v1/ontology/query",
        json={
            "entity_type": "RecipeVariant",
            "anchor_names": [recipes["name"]],
            "numeric_conditions": [
                {
                    "property": "ingredientTotalAmount",
                    "target_ref": "糖类",
                    "grain": "recipe_total",
                    "op": "lte",
                    "value": "12",
                    "unit": "g",
                }
            ],
            "numeric_selections": [
                {
                    "property": "ingredientTotalAmount",
                    "target_ref": "糖类",
                    "grain": "recipe_total",
                    "unit": "g",
                }
            ],
        },
    )
    assert numeric.status_code == 200, numeric.text
    assert numeric.json()["total"] == 1
    assert numeric.json()["numeric_values"]
    job = api.get("/api/v1/knowledge/jobs/" + recipes["receipts"][0]["job_id"])
    assert job.status_code == 200 and job.json()["status"] == "graph_ready"


def test_natural_language_numeric_count_scope_and_unit_conversion(api, recipes):
    queries = [
        (recipes["name"] + "共有多少个做法版本？", r"共有\s*2\s*条"),
        (f"只统计{recipes['name']}中糖类合计用量不超过12克的做法，共有多少份？", r"共有\s*1\s*条"),
        (
            f"列出{recipes['name']}中糖类合计用量不超过12克的做法，并把用量换算成毫克。",
            r"10000\s*mg",
        ),
    ]
    for question, expected in queries:
        response = api.post("/api/v1/knowledge/query", json={"question": question})
        assert response.status_code == 200, response.text
        result = response.json()
        assert re.search(expected, result["message"]), result["message"]
        assert result["metadata"]["model_calls"] == 1


def test_chat_clarification_followup_unknown_and_no_hallucinated_sugar(api, recipes):
    first = api.post("/api/v1/chat/", json={"message": recipes["name"] + "加多少白糖？"})
    assert first.status_code == 200, first.text
    choice = first.json()
    assert choice["route"] == "clarification" and len(choice["metadata"]["choices"]) == 2
    selected = api.post(
        "/api/v1/chat/", json={"session_id": choice["session_id"], "message": "第1份"}
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["sources"] and selected.json()["metadata"]["model_calls"] <= 1
    assert any(amount in selected.json()["message"] for amount in ("10", "20"))
    unknown = api.post("/api/v1/chat/", json={"message": recipes["unknown"] + "加多少白糖？"})
    assert unknown.status_code == 200 and "适量" in unknown.json()["message"]
    missing = api.post("/api/v1/chat/", json={"message": "佛跳墙加多少糖？"})
    assert missing.status_code == 200, missing.text
    assert any(word in missing.json()["message"] for word in ("未记录", "未记载", "没有", "未找到"))
    (EVIDENCE / "fact-answers.json").write_text(
        json.dumps(
            {
                "clarify": choice,
                "selected": selected.json(),
                "qualitative": unknown.json(),
                "missing": missing.json(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_mysql_session_message_snapshot_and_validation_rollback(api):
    session_id, user = "acceptance-" + uuid4().hex, "acceptance-user-" + uuid4().hex
    created = api.post(
        "/api/v1/sessions/", json={"id": session_id, "title": "验收会话", "user_id": user}
    )
    assert created.status_code == 201, created.text
    assert api.patch("/api/v1/sessions/" + session_id, json={"title": None}).status_code == 422
    assert api.get("/api/v1/sessions/" + session_id).json()["title"] == "验收会话"
    changed = api.patch("/api/v1/sessions/" + session_id, json={"title": "修改成功"})
    assert changed.status_code == 200 and changed.json()["title"] == "修改成功"
    message = api.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "session_id": session_id,
            "message_type": "user_query",
            "content": "持久化验收",
            "order_index": 0,
        },
    )
    assert message.status_code == 201 and message.json()["content"] == "持久化验收"
    snap = api.post(
        f"/api/v1/sessions/{session_id}/snapshot",
        json={
            "session_id": session_id,
            "query": "验收",
            "response_data": {"message": "已记录", "count": 0},
        },
    )
    assert snap.status_code == 201 and snap.json()["response_data"]["count"] == 0
    assert api.get(f"/api/v1/sessions/user/{user}/count").json()["session_count"] == 1
    assert len(api.get("/api/v1/sessions/", params={"user_id": user}).json()) == 1
    assert len(api.get("/api/v1/chat/history/" + session_id).json()) == 1
    assert api.delete("/api/v1/chat/session/" + session_id).status_code == 200
    assert api.get("/api/v1/chat/history/" + session_id).json() == []
    assert api.delete("/api/v1/sessions/" + session_id).status_code == 204
    assert api.get("/api/v1/sessions/", params={"user_id": user}).json() == []


def test_real_embedding_retrieval_rerank_generation_revision_and_withdrawal(api):
    token = uuid4().hex[:10]
    source = "acceptance-doc-" + token
    text = f"软件验收原文{token}：青柚联调酱用于给蒸鱼提鲜，应该在蒸鱼出锅后少量淋入。此为软件测试资料，不是真实烹饪建议。"
    upload = api.post(
        "/api/v1/upload/file", files={"file": ("acceptance.txt", text.encode(), "text/plain")}
    )
    assert upload.status_code == 200, upload.text
    asset = upload.json()
    try:
        assert api.get(asset["file_url"]).content == text.encode()
        payload = {
            "asset_id": asset["asset_id"],
            "source_id": source,
            "uri": "acceptance://docs/" + token,
        }
        ingested = api.post("/api/v1/knowledge/documents", json=payload)
        assert ingested.status_code == 201, ingested.text
        assert ingested.json()["details"]["document"]["embedded"] >= 1
        repeated = api.post("/api/v1/knowledge/documents", json=payload)
        assert (
            repeated.status_code == 201 and repeated.json()["details"]["document"]["embedded"] == 0
        )
        started = perf_counter()
        answer = api.post(
            "/api/v1/knowledge/query",
            json={
                "question": "只依据知识库原文说明青柚联调酱有什么用途、什么时候加入，并引用来源。",
            },
        )
        assert answer.status_code == 200, answer.text
        data = answer.json()
        assert "蒸鱼" in data["message"] and "出锅" in data["message"] and data["sources"]
        calls = data["metadata"]["provider_calls"]
        assert calls["document"]["http_attempts"] >= 1 and calls["rerank"]["http_attempts"] >= 1
        assert data["metadata"]["model_calls"] <= 2
        assert "semantic_evaluation" not in data["message"]
        with api.stream(
            "POST", "/api/v1/chat/stream", json={"message": "只根据原文说青柚联调酱何时加入。"}
        ) as stream:
            assert stream.status_code == 200
            events = [
                json.loads(line[6:]) for line in stream.iter_lines() if line.startswith("data: ")
            ]
        assert events[-1]["type"] == "done" and events[-1]["sources"]
        assert "出锅" in events[-1]["message"]
        assert events[-1]["metadata"]["generation_calls"] == 1
        assert events[-1]["message"] == "".join(
            e["content"] for e in events if e["type"] == "message"
        )
        (EVIDENCE / "live-document-answer.json").write_text(
            json.dumps(
                {"seconds": round(perf_counter() - started, 3), "answer": data},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        revised = api.post(
            "/api/v1/knowledge/documents",
            json={"text": text + "修订补充：测试批次为甲。", "source_id": source},
        )
        assert (
            revised.status_code == 201 and revised.json()["version"] != ingested.json()["version"]
        )
    finally:
        try:
            withdrawn = api.delete("/api/v1/knowledge/sources/" + source)
            assert withdrawn.status_code in {200, 404}
        finally:
            assert api.delete("/api/v1/upload/" + asset["asset_id"]).status_code == 200
    assert api.get(asset["file_url"]).status_code == 404


def test_real_ontology_extraction_evidence_shapes_insert_and_query(api):
    token = uuid4().hex[:8]
    source = "acceptance-extract-" + token
    name = "联调清炖鸡" + token
    extracted = api.post(
        "/api/v1/ontology/extract",
        json={
            "sources": [
                {
                    "id": source,
                    "uri": "acceptance://extract/" + token,
                    "text": f"{name}这份做法使用鸡肉100克，辅料白糖10克。第一步准备食材，第二步炖煮。记载耗时半小时。",
                }
            ]
        },
    )
    assert extracted.status_code == 200, extracted.text
    graph = extracted.json()
    (EVIDENCE / "extracted-graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    assert graph["entities"] and graph["relations"]
    assert api.post("/api/v1/ontology/validate", json=graph).status_code == 200
    invalid = json.loads(json.dumps(graph))
    invalid["entities"][0]["evidence"][0]["quote"] = "完全不在来源中的伪造引文"
    assert api.post("/api/v1/ontology/validate", json=invalid).status_code == 422
    assert api.post("/api/v1/ontology/facts", json=graph).status_code == 200
    variant = next(entity for entity in graph["entities"] if entity["type"] == "RecipeVariant")
    assert "联调清炖鸡" in variant["name"]
    query = api.post(
        "/api/v1/ontology/query",
        json={"entity_type": "RecipeVariant", "anchor_ids": [variant["id"]]},
    )
    assert query.status_code == 200 and query.json()["total"] == 1
    assert query.json()["entities"][0]["id"] == variant["id"]


@pytest.mark.parametrize("format", ["md", "json", "csv", "pdf", "scanned-pdf", "docx"])
def test_managed_upload_document_formats(api, format):
    if format in {"pdf", "scanned-pdf"}:
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=100)
        if format == "pdf":
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {
                            NameObject("/F1"): DictionaryObject(
                                {
                                    NameObject("/Type"): NameObject("/Font"),
                                    NameObject("/Subtype"): NameObject("/Type1"),
                                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                                }
                            )
                        }
                    )
                }
            )
            contents = DecodedStreamObject()
            contents.set_data(b"BT /F1 12 Tf 10 70 Td (Live acceptance text document.) Tj ET")
            page[NameObject("/Contents")] = writer._add_object(contents)
        output = io.BytesIO()
        writer.write(output)
        content = output.getvalue()
    elif format == "docx":
        from docx import Document

        document = Document()
        document.add_paragraph("软件验收文档：测试原文可以解析与向量化。")
        output = io.BytesIO()
        document.save(output)
        content = output.getvalue()
    else:
        content = {
            "md": "# 验收资料\n测试资料原文。",
            "json": '{"说明":"验收资料"}',
            "csv": "菜名,说明\n验收菜,示例原文",
        }[format].encode()
    extension = "pdf" if format == "scanned-pdf" else format
    upload = api.post("/api/v1/upload/file", files={"file": ("acceptance." + extension, content)})
    assert upload.status_code == 200, upload.text
    asset, source = upload.json(), "acceptance-format-" + uuid4().hex
    try:
        response = api.post(
            "/api/v1/knowledge/documents", json={"asset_id": asset["asset_id"], "source_id": source}
        )
        assert response.status_code == (422 if format == "scanned-pdf" else 201), response.text
    finally:
        try:
            if format != "scanned-pdf":
                assert api.delete("/api/v1/knowledge/sources/" + source).status_code in {200, 404}
        finally:
            assert api.delete("/api/v1/upload/" + asset["asset_id"]).status_code == 200


def test_stream_events_and_concurrent_request_isolation(api):
    with api.stream("POST", "/api/v1/chat/stream", json={"message": "你好"}) as response:
        assert response.status_code == 200
        events = [
            json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")
        ]
    assert events[-1]["type"] == "done"
    assert events[-1]["message"] == "".join(
        event["content"] for event in events if event["type"] == "message"
    )
    assert len(api.get("/api/v1/chat/history/" + events[-1]["session_id"]).json()) == 2

    def greet(index):
        with httpx.Client(base_url=BASE_URL, timeout=30, trust_env=False) as client:
            response = client.post(
                "/api/v1/chat/", json={"message": "你好", "user_id": "concurrent-" + str(index)}
            )
            assert response.status_code == 200
            return response.json()

    with ThreadPoolExecutor(max_workers=3) as pool:
        answers = list(pool.map(greet, range(3)))
    assert len({answer["session_id"] for answer in answers}) == 3
    assert all(answer["metadata"]["model_calls"] == 0 for answer in answers)


def test_invalid_paths_types_and_unsupported_fact_scope_are_rejected(api):
    assert (
        api.post("/api/v1/upload/file", files={"file": ("payload.exe", b"test")}).status_code == 400
    )
    assert (
        api.post("/api/v1/upload/file", files={"file": ("../private.txt", b"test")}).status_code
        == 400
    )
    assert api.post(
        "/api/v1/chat/", json={"message": "read", "file_path": "E:/GustoBot/.env"}
    ).status_code in {400, 404}
    assert (
        api.post("/api/v1/ontology/query", json={"entity_type": "ImaginaryType"}).status_code == 422
    )
    assert (
        api.post("/api/v1/knowledge/documents", json={"asset_id": "does-not-exist"}).status_code
        == 404
    )


def test_uploaded_image_roundtrip_and_type_validation(api):
    from PIL import Image

    stream = io.BytesIO()
    Image.new("RGB", (4, 4), color="white").save(stream, format="PNG")
    response = api.post(
        "/api/v1/upload/image", files={"image": ("acceptance.png", stream.getvalue(), "image/png")}
    )
    assert response.status_code == 200, response.text
    uploaded = response.json()
    try:
        assert api.get(uploaded["image_url"]).content == stream.getvalue()
    finally:
        assert api.delete("/api/v1/upload/" + uploaded["asset_id"]).status_code == 200
    assert api.get(uploaded["image_url"]).status_code == 404
