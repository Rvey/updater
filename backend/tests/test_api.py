from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import main
from app.db import Base


def test_republish_merges_and_questions_stay_with_feature(tmp_path) -> None:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)

    def test_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    payload = {
        "external_id": "example/repo:search",
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
            "publish_feature", "list_feature_updates", "get_feature_update", "add_feature_impact", "list_context_requests", "claim_context_request", "fulfill_context_request",
            "report_tech_debt", "list_tech_debt", "get_tech_debt", "update_tech_debt",
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


def test_republish_merges_commits_under_one_feature(tmp_path) -> None:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'merge.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)

    def test_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    base = {
        "external_id": "example/repo:user-auth",
        "title": "User auth", "summary": "Users can now sign in with email.",
        "repo_url": "https://github.com/example/repo", "why": "Users needed accounts.",
        "how_it_works": "The login endpoint issues sessions.",
        "impact": "Users stay signed in.", "branch": "rvey/user-auth",
    }
    try:
        with TestClient(main.app) as client:
            first = client.post("/api/updates", json={
                **base, "commit_sha": "aaa", "files_changed": ["src/auth.ts"],
                "tags": ["auth"],
                "code_context": [{"path": "src/auth.ts", "content": "login()", "start_line": 1, "end_line": 5}],
            })
            assert first.status_code == 201, first.text
            second = client.post("/api/updates", json={
                **base, "commit_sha": "bbb", "files_changed": ["src/session.ts"],
                "tags": ["auth", "session"],
                "code_context": [{"path": "src/session.ts", "content": "refresh()", "start_line": 9, "end_line": 12}],
            })
            assert second.status_code == 201, second.text
            assert second.json()["id"] == first.json()["id"]
            body = second.json()
            assert body["commit_sha"] == "bbb"
            assert body["files_changed"] == ["src/auth.ts", "src/session.ts"]
            assert body["tags"] == ["auth", "session"]
            assert [e["path"] for e in body["code_context"]] == ["src/auth.ts", "src/session.ts"]
            assert body["title"] == "User auth"
            listed = client.get("/api/updates", params={"q": "sign in"})
            assert len(listed.json()) == 1
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()


def test_notes_ticket_fields(tmp_path) -> None:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'notes.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)

    def test_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    try:
        with TestClient(main.app) as client:
            created = client.post("/api/notes", json={
                "title": "Fix retry", "content": "Retry duplicates tool calls",
                "category": "bug", "status": "open", "priority": "high",
                "tags": ["backend"], "repository": "ai-voice-agent",
                "branch": "fix/x", "pinned": True,
            })
            assert created.status_code == 201, created.text
            body = created.json()
            assert body["category"] == "bug"
            assert body["priority"] == "high"
            assert body["pinned"] is True
            assert client.post("/api/notes", json={"title": "x", "category": "nope"}).status_code == 422
            note_id = body["id"]
            patched = client.patch(f"/api/notes/{note_id}", json={"status": "done", "tags": ["backend", "fix"]})
            assert patched.status_code == 200, patched.text
            assert patched.json()["status"] == "done"
            assert patched.json()["tags"] == ["backend", "fix"]
            listed = client.get("/api/notes")
            assert listed.status_code == 200
            assert listed.json()[0]["id"] == note_id
            assert client.delete(f"/api/notes/{note_id}").status_code == 200
            assert client.get("/api/notes").json() == []
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()


def test_tech_debt_crud_and_filters(tmp_path) -> None:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'techdebt.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)

    def test_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    payload = {
        "title": "Retry duplicates tool calls",
        "scope": "backend worker retry path",
        "description": "The worker retries without idempotency keys, so a timeout can enqueue the same job twice.",
        "impact": "Duplicate side effects in production and noisy logs when the queue backs up.",
        "mitigation": "Add idempotency keys and make the handler check-then-insert inside one transaction.",
        "current_state": "Retries succeed for now; duplicates are cleaned up manually once a day.",
        "urgency": "high",
        "repo_url": "https://github.com/example/repo",
        "file_path": "backend/worker.py",
        "files": ["backend/worker.py"],
        "tags": ["reliability"],
    }
    try:
        with TestClient(main.app) as client:
            created = client.post("/api/tech-debt", json=payload)
            assert created.status_code == 201, created.text
            body = created.json()
            assert body["urgency"] == "high"
            assert body["status"] == "open"
            debt_id = body["id"]
            assert client.post("/api/tech-debt", json={**payload, "urgency": "nope"}).status_code == 422
            fetched = client.get(f"/api/tech-debt/{debt_id}")
            assert fetched.status_code == 200
            assert fetched.json()["scope"] == "backend worker retry path"
            filtered = client.get("/api/tech-debt", params={"q": "idempotency"})
            assert filtered.status_code == 200
            assert [item["id"] for item in filtered.json()] == [debt_id]
            assert client.get("/api/tech-debt", params={"urgency": "low"}).json() == []
            patched = client.patch(f"/api/tech-debt/{debt_id}", json={"status": "in-progress"})
            assert patched.status_code == 200, patched.text
            assert patched.json()["status"] == "in-progress"
            resolved = client.patch(f"/api/tech-debt/{debt_id}", json={"status": "resolved"})
            assert resolved.json()["resolved_at"] is not None
            assert client.delete(f"/api/tech-debt/{debt_id}").status_code == 200
            assert client.get("/api/tech-debt").json() == []
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()


def test_claim_and_wrong_project_rejected(tmp_path) -> None:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'claim.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)

    def test_db():
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    try:
        with TestClient(main.app) as client:
            created = client.post("/api/updates", json={
                "title": "Claim test", "summary": "A feature for claim flow.",
                "repo_url": "https://github.com/example/repo", "why": "Owners need routing.",
                "how_it_works": "Watcher claims then fulfills.",
                "impact": "No wrong-project excerpts.",
            })
            assert created.status_code == 201, created.text
            update_id = created.json()["id"]
            req = client.post(f"/api/updates/{update_id}/context-requests", json={"question": "Where is x?"})
            assert req.status_code == 201, req.text
            rid = req.json()["id"]
            claimed = client.post(f"/api/context-requests/{rid}/claim", json={"agent": "opencode"})
            assert claimed.status_code == 200, claimed.text
            assert claimed.json()["status"] == "claimed"
            assert claimed.json()["claimed_by"] == "opencode"
            again = client.post(f"/api/context-requests/{rid}/claim", json={"agent": "other"})
            assert again.json()["status"] == "claimed"
            assert again.json()["claimed_by"] == "opencode"
            bad = client.post(f"/api/context-requests/{rid}/fulfill", json={
                "excerpts": [{"path": "a.ts", "content": "x", "start_line": 1, "end_line": 2}],
                "repo_url": "https://github.com/other/wrong",
            })
            assert bad.status_code == 409, bad.text
            good = client.post(f"/api/context-requests/{rid}/fulfill", json={
                "excerpts": [{"path": "a.ts", "content": "x", "start_line": 1, "end_line": 2}],
                "repo_url": "https://github.com/example/repo.git",
                "branch": "main",
                "commit_sha": "abc123",
            })
            assert good.status_code == 200, good.text
            assert good.json()["status"] == "fulfilled"
            assert good.json()["source_branch"] == "main"
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()
