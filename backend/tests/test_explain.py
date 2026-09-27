import asyncio
import json
from types import SimpleNamespace

import httpx

from app import explain
from app.db import Update


def test_explanation_uses_openrouter_chat_completions(monkeypatch) -> None:
    settings = SimpleNamespace(openrouter_api_key="test-openrouter-key", llm_model="google/gemini-3.5-flash-lite")
    monkeypatch.setattr(explain, "get_settings", lambda: settings)

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-openrouter-key"
        body = json.loads(request.content)
        assert body["model"] == settings.llm_model
        assert body["messages"][0]["role"] == "system"
        assert "Why was it built?" in body["messages"][1]["content"]
        assert "Users needed faster search" in body["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "It saves users time."}}]})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(explain.httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs))
    update = Update(
        title="Faster search",
        summary="Search is faster.",
        repo_url="https://github.com/example/repo",
        why="Users needed faster search",
        how_it_works="The client sends a debounced query.",
        impact="Users find projects faster.",
        tradeoffs="",
        learning_notes="",
        files_changed=["src/search.ts"],
    )

    assert asyncio.run(explain.explain_question(update, "Why was it built?")) == ("It saves users time.", "ai")
