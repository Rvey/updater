from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import main
from app.db import Base


def test_publish_is_idempotent_and_questions_stay_with_feature(tmp_path) -> None:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)

    def test_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    payload = {
        "external_id": "example/repo:abc123:search",
        "title": "Faster project search",
        "summary": "Project search now filters results as users type.",
        "repo_url": "https://github.com/example/repo",
        "why": "Users had to scan the full project list to find a workspace.",
        "how_it_works": "The client sends a debounced query to the indexed project endpoint.",
        "impact": "Users can locate projects with fewer steps and less waiting.",
        "files_changed": ["src/search.ts"],
        "tags": ["search"],
    }
    try:
        with TestClient(main.app) as client:
            first = client.post("/api/updates", json=payload)
            assert first.status_code == 201, first.text
            second = client.post("/api/updates", json=payload)
            assert second.status_code == 201
            assert second.json()["id"] == first.json()["id"]

            update_id = first.json()["id"]
            answer = client.post(f"/api/updates/{update_id}/questions", json={"question": "Why was this built?"})
            assert answer.status_code == 201, answer.text
            assert "Users had to scan" in answer.json()["answer"]
            assert answer.json()["source"] == "saved-context"

            listed = client.get("/api/updates", params={"q": "debounced"})
            assert listed.status_code == 200
            assert len(listed.json()) == 1
            assert len(listed.json()[0]["questions"]) == 1
            observation = client.post(f"/api/updates/{update_id}/impact-notes", json={"note": "Search time dropped after release."})
            assert observation.status_code == 201
            assert client.get(f"/api/updates/{update_id}").json()["impact_notes"][0]["note"] == "Search time dropped after release."
            assert client.get("/api/updates", params={"repo": "https://github.com/other/repo"}).json() == []
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()


def test_invalid_repository_is_rejected(tmp_path) -> None:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)

    def test_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    try:
        with TestClient(main.app) as client:
            response = client.post("/api/updates", json={
                "title": "A new feature", "summary": "A useful change was shipped.",
                "repo_url": "not-a-link", "why": "A real user problem needed to be solved.",
                "how_it_works": "The service creates and stores the new record.",
                "impact": "It should reduce manual work for the user.",
            })
            assert response.status_code == 422
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()


def test_token_protects_api(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "updater_token", "test-secret")
    with TestClient(main.app) as client:
        assert client.get("/api/updates").status_code == 401
        assert client.get("/api/updates", headers={"Authorization": "Bearer test-secret"}).status_code == 200
        assert client.post("/mcp", json={}).status_code == 401


def test_http_mcp_lists_feature_tools(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "mcp_allowed_hosts", "updater.example.test")
    with TestClient(main.app, base_url="https://updater.example.test") as client:
        response = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "updater-test", "version": "1"},
            }},
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["serverInfo"]["name"] == "Updater"
        tools = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert tools.status_code == 200, tools.text
        assert {tool["name"] for tool in tools.json()["result"]["tools"]} == {
            "publish_feature", "list_feature_updates", "get_feature_update", "add_feature_impact", "list_context_requests", "fulfill_context_request",
        }
def test_agent_proxy_context_flow(tmp_path) -> None:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'proxy.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)

    def test_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    try:
        with TestClient(main.app) as client:
            created = client.post("/api/updates", json={
                "title": "Proxy context feature", "summary": "A feature that needs code excerpts.",
                "repo_url": "https://github.com/example/repo", "why": "Owners need code-level answers.",
                "how_it_works": "The agent proxy supplies excerpts on demand.",
                "impact": "Questions get answered with real code.",
                "files_changed": ["src/search.ts"],
            })
            assert created.status_code == 201, created.text
            update_id = created.json()["id"]
            assert created.json()["code_context"] == []
            requested = client.post(f"/api/updates/{update_id}/context-requests", json={"question": "Where is the debounce implemented?"})
            assert requested.status_code == 201, requested.text
            request_id = requested.json()["id"]
            assert requested.json()["status"] == "pending"
            pending = client.get("/api/context-requests", params={"repo": "https://github.com/example/repo"})
            assert pending.status_code == 200
            assert [item["id"] for item in pending.json()] == [request_id]
            fulfilled = client.post(f"/api/context-requests/{request_id}/fulfill", json={"excerpts": [
                {"path": "src/search.ts", "content": "setTimeout(fetchResults, 150)", "start_line": 10, "end_line": 12},
            ]})
            assert fulfilled.status_code == 200, fulfilled.text
            assert fulfilled.json()["status"] == "fulfilled"
            fetched = client.get(f"/api/updates/{update_id}")
            assert fetched.status_code == 200
            assert fetched.json()["code_context"][0]["path"] == "src/search.ts"
            assert fetched.json()["context_requests"][0]["status"] == "fulfilled"
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()
