"""
Compatibility contract tests.

These tests intentionally avoid calling external services (LLMs, databases).
They only verify that we keep stable public-facing interfaces (routes/env vars)
even as internals evolve.
"""

import sys
from pathlib import Path
from typing import Set, Tuple

from fastapi import FastAPI
from starlette.routing import Route

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _collect_route_methods(app: FastAPI) -> Set[Tuple[str, str]]:
    methods: Set[Tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, Route) or route.methods is None:
            continue
        for method in route.methods:
            methods.add((route.path, method))
    return methods


def test_chat_api_exposes_legacy_alias_routes() -> None:
    """
    Keep backward-compatible endpoints:

    - New canonical endpoints:
      - POST /api/v1/chat/
      - POST /api/v1/chat/stream

    - Legacy endpoints referenced by older docs/scripts:
      - POST /api/v1/chat/chat
      - GET  /api/v1/chat/chat/stream (SSE)
      - POST /api/v1/chat/chat/stream
    """

    from gustobot.main import application

    routes = _collect_route_methods(application)

    assert ("/api/v1/chat/", "POST") in routes
    assert ("/api/v1/chat/stream", "POST") in routes

    # Legacy aliases
    assert ("/api/v1/chat/chat", "POST") in routes
    assert ("/api/v1/chat/chat/stream", "GET") in routes
    assert ("/api/v1/chat/chat/stream", "POST") in routes


def test_settings_accept_openai_env_var_aliases(monkeypatch) -> None:
    """
    The codebase uses Settings.LLM_* but older deployments use OPENAI_*.
    Support both to reduce migration friction.
    """

    # Ensure the canonical LLM_* vars are not set (other tests may load `.env`).
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_API_BASE", "http://example.local/v1")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    # Import late so env is set before instantiation.
    from gustobot.config.settings import Settings

    settings = Settings(_env_file=None)

    assert settings.LLM_API_KEY == "test-openai-key"
    assert settings.LLM_BASE_URL == "http://example.local/v1"
    assert settings.LLM_MODEL == "test-model"
