#!/usr/bin/env python3
"""Probe current backend contracts; default checks never ingest knowledge or call models.

Use --exercise-chat to write and clear a probe conversation in the selected app.
This is a deployment smoke check, not a claim of exhaustive API coverage.
"""

import argparse
import json
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def test_backend(*, base_url: str, exercise_chat: bool = False) -> list[CheckResult]:
    results = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=30, trust_env=False) as client:
        for path in (
            "/health",
            "/api",
            "/openapi.json",
            "/api/v1/ontology/domain",
            "/api/v1/chat/routes",
        ):
            try:
                response = client.get(path)
                response.raise_for_status()
                data = response.json()
                if path == "/openapi.json":
                    paths = data["paths"]
                    required = {
                        "/api/v1/knowledge/documents",
                        "/api/v1/ontology/facts",
                        "/api/v1/chat/stream",
                    }
                    if not required <= paths.keys() or any("lightrag" in name for name in paths):
                        raise ValueError("Current unified API contracts are not registered")
                if (
                    path.endswith("/ontology/domain")
                    and not {"classes", "allowed_edges", "lexicon"} <= data.keys()
                ):
                    raise ValueError("Semantic ontology fields are missing")
                results.append(CheckResult(f"GET {path}", True))
            except (httpx.HTTPError, ValueError, KeyError) as error:
                results.append(CheckResult(f"GET {path}", False, str(error)))
        if not exercise_chat:
            return results
        session_id = None
        try:
            response = client.post("/api/v1/chat/", json={"message": "你好"})
            response.raise_for_status()
            answer = response.json()
            session_id = answer["session_id"]
            if answer["route"] != "general-query" or answer["metadata"].get("model_calls") != 0:
                raise ValueError("Greeting did not use the deterministic response")
            history = client.get(f"/api/v1/chat/history/{session_id}")
            history.raise_for_status()
            if len(history.json()) != 2:
                raise ValueError("Probe conversation was not persisted")
            with client.stream(
                "POST", "/api/v1/chat/stream", json={"message": "你好", "session_id": session_id}
            ) as stream:
                stream.raise_for_status()
                completed = False
                for line in stream.iter_lines():
                    if line.startswith("data:"):
                        event = json.loads(line[5:].strip())
                        if event.get("type") == "error":
                            raise ValueError("Chat stream returned an error")
                        if event.get("type") == "done":
                            completed = True
                if not completed:
                    raise ValueError("Chat stream did not finish")
            results.append(CheckResult("Chat persistence and SSE", True))
        except (httpx.HTTPError, ValueError, KeyError) as error:
            results.append(CheckResult("Chat persistence and SSE", False, str(error)))
        finally:
            if session_id is not None:
                try:
                    response = client.delete(f"/api/v1/chat/session/{session_id}")
                    response.raise_for_status()
                except httpx.HTTPError as error:
                    results.append(CheckResult("Clear probe conversation", False, str(error)))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--exercise-chat", action="store_true", help="Create and clear one probe conversation"
    )
    args = parser.parse_args(argv)
    results = test_backend(base_url=args.base_url, exercise_chat=args.exercise_chat)
    for result in results:
        print(
            f"[{'OK' if result.ok else 'FAIL'}] {result.name}"
            + (f": {result.detail}" if result.detail else "")
        )
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
