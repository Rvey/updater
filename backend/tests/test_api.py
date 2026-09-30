from collections.abc import Generator
from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app import mcp_server
from app import backfill_ownership
from app.db import Base
from app.db import Note
from app.db import Update
from app.db import User
from app import auth as auth_utils


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


def test_updates_with_matching_timestamps_have_stable_batch_order(tmp_path) -> None:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)
    timestamp = datetime(2026, 9, 28, tzinfo=timezone.utc)

    with session_factory() as session:
        for update_id in ("a", "b", "c"):
            session.add(main.Update(
                id=update_id,
                title=f"Update {update_id}",
                summary="A shipped update with the same timestamp.",
                repo_url="https://github.com/example/repo",
                why="This records the reason for the change.",
                how_it_works="The service stores the update.",
                impact="Users can review the update later.",
                shipped_at=timestamp,
                created_at=timestamp,
            ))
        session.commit()

    def test_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    try:
        with TestClient(main.app) as client:
            first = client.get("/api/updates", params={"limit": 2, "offset": 0})
            second = client.get("/api/updates", params={"limit": 2, "offset": 2})
            assert first.status_code == second.status_code == 200
            assert [item["id"] for item in first.json() + second.json()] == ["c", "b", "a"]
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


def test_tasks_board_crud_reorder_and_delete(tmp_path) -> None:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'tasks.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)

    def test_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    try:
        with TestClient(main.app) as client:
            first = client.post("/api/tasks", json={
                "title": "Ship the kanban board",
                "description": "Wire drag and drop to the API.",
                "priority": "high",
                "repo_url": "https://github.com/example/repo",
                "tags": ["Frontend", "board"],
                "assignee": "Rvey",
                "due_date": "2026-10-01T00:00:00Z",
            })
            assert first.status_code == 201, first.text
            body = first.json()
            assert body["status"] == "backlog"
            assert body["position"] == 0
            assert body["tags"] == ["frontend", "board"]
            assert body["completed_at"] is None
            first_id = body["id"]

            second = client.post("/api/tasks", json={"title": "Add task API", "status": "in-progress", "priority": "medium"})
            assert second.status_code == 201, second.text
            second_id = second.json()["id"]

            third = client.post("/api/tasks", json={"title": "Review the board", "status": "in-progress"})
            assert third.status_code == 201, third.text
            third_id = third.json()["id"]
            assert third.json()["position"] == 1

            assert client.post("/api/tasks", json={"title": "Bad status", "status": "nope"}).status_code == 422
            assert client.post("/api/tasks", json={"title": "Bad priority", "priority": "nope"}).status_code == 422

            fetched = client.get(f"/api/tasks/{first_id}")
            assert fetched.status_code == 200
            assert fetched.json()["assignee"] == "Rvey"

            board = client.post("/api/tasks/reorder", json={"columns": {
                "backlog": [],
                "in-progress": [first_id, second_id],
                "review": [],
                "done": [third_id],
            }})
            assert board.status_code == 200, board.text
            by_id = {item["id"]: item for item in board.json()}
            assert by_id[first_id]["status"] == "in-progress"
            assert by_id[first_id]["position"] == 0
            assert by_id[second_id]["position"] == 1
            assert by_id[third_id]["status"] == "done"
            assert by_id[third_id]["completed_at"] is not None

            patched = client.patch(f"/api/tasks/{third_id}", json={"status": "review", "title": "Review the board v2"})
            assert patched.status_code == 200, patched.text
            assert patched.json()["status"] == "review"
            assert patched.json()["completed_at"] is None
            assert patched.json()["title"] == "Review the board v2"

            cleared = client.patch(f"/api/tasks/{first_id}", json={"repo_url": None, "due_date": None})
            assert cleared.status_code == 200, cleared.text
            assert cleared.json()["repo_url"] is None
            assert cleared.json()["due_date"] is None

            assert [item["id"] for item in client.get("/api/tasks", params={"q": "kanban"}).json()] == [first_id]
            assert client.get("/api/tasks", params={"priority": "high"}).json()[0]["id"] == first_id
            assert client.get("/api/tasks", params={"repo": "https://github.com/example/repo"}).json() == []

            assert client.delete(f"/api/tasks/{second_id}").status_code == 200
            remaining = client.get("/api/tasks").json()
            assert second_id not in {item["id"] for item in remaining}
            in_progress = [item for item in remaining if item["status"] == "in-progress"]
            assert [item["position"] for item in in_progress] == [0]

            missing = client.post("/api/tasks/reorder", json={"columns": {"backlog": ["missing"]}})
            assert missing.status_code == 404
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


def _signed_in_client(test_engine, **client_kwargs) -> TestClient:
    """TestClient whose API calls carry a per-account key instead of the shared token."""
    session_factory = sessionmaker(bind=test_engine)

    def test_db():
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    return TestClient(main.app, **client_kwargs)


def _register_account(client: TestClient, email: str) -> str:
    """Register one account and return an `upk_` agent key that identifies it."""
    registered = client.post("/api/auth/register", json={"email": email, "password": "correct horse battery"})
    assert registered.status_code == 201, registered.text
    session_token = registered.json()["session_token"]
    created_key = client.post(
        "/api/auth/keys",
        json={"name": email.split("@")[0]},
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert created_key.status_code == 201, created_key.text
    return created_key.json()["key"]


def test_accounts_only_see_their_own_updates(tmp_path) -> None:
    """An agent key must scope updates to its account instead of exposing everyone's work."""
    test_engine = create_engine(f"sqlite:///{tmp_path / 'ownership.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    client = _signed_in_client(test_engine)
    base = {
        "summary": "A shipped change recorded for one account only.",
        "repo_url": "https://github.com/example/repo",
        "why": "Each account keeps its own update history.",
        "how_it_works": "The API stores the owning account id on every update.",
        "impact": "Agents stop seeing unrelated accounts' updates.",
    }
    try:
        with client:
            alpha = _register_account(client, "alpha@example.com")
            beta = _register_account(client, "beta@example.com")
            alpha_headers = {"Authorization": f"Bearer {alpha}"}
            beta_headers = {"Authorization": f"Bearer {beta}"}

            created = client.post("/api/updates", json={**base, "title": "Alpha only", "external_id": "example/repo:alpha"}, headers=alpha_headers)
            assert created.status_code == 201, created.text
            alpha_update_id = created.json()["id"]
            assert created.json()["user_id"] is not None

            # Beta sees an empty board and cannot read Alpha's entry by id.
            assert client.get("/api/updates", headers=beta_headers).json() == []
            assert client.get(f"/api/updates/{alpha_update_id}", headers=beta_headers).status_code == 404
            assert client.post(f"/api/updates/{alpha_update_id}/impact-notes", json={"note": "nope"}, headers=beta_headers).status_code == 404
            assert client.post(f"/api/updates/{alpha_update_id}/context-requests", json={"question": "Where?"}, headers=beta_headers).status_code == 404

            # Alpha still sees its own update, plus anything an agent republishes.
            listed = client.get("/api/updates", headers=alpha_headers).json()
            assert [item["id"] for item in listed] == [alpha_update_id]
            republished = client.post("/api/updates", json={**base, "title": "Alpha only", "external_id": "example/repo:alpha", "commit_sha": "abc"}, headers=alpha_headers)
            assert republished.status_code == 201, republished.text
            assert republished.json()["id"] == alpha_update_id

            # A second account republishing the same feature key must not merge into Alpha's entry.
            beta_created = client.post("/api/updates", json={**base, "title": "Beta only", "external_id": "example/repo:alpha"}, headers=beta_headers)
            assert beta_created.status_code == 409, beta_created.text
            assert client.get("/api/updates", headers=alpha_headers).json()[0]["commit_sha"] == "abc"

            # The shared env token keeps the legacy unrestricted view.
            main.settings.updater_token = "shared-secret"
            try:
                everything = client.get("/api/updates", headers={"Authorization": "Bearer shared-secret"})
                assert [item["id"] for item in everything.json()] == [alpha_update_id]
            finally:
                main.settings.updater_token = ""
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()


def test_notes_tasks_and_tech_debt_are_scoped_per_account(tmp_path) -> None:
    """Notes, tasks and tech debt must honour the same account scoping as updates."""
    test_engine = create_engine(f"sqlite:///{tmp_path / 'scoped.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    client = _signed_in_client(test_engine)
    try:
        with client:
            alpha = _register_account(client, "alpha@example.com")
            beta = _register_account(client, "beta@example.com")
            alpha_headers = {"Authorization": f"Bearer {alpha}"}
            beta_headers = {"Authorization": f"Bearer {beta}"}

            note = client.post("/api/notes", json={"title": "Alpha note", "content": "private"}, headers=alpha_headers)
            assert note.status_code == 201, note.text
            assert client.get("/api/notes", headers=beta_headers).json() == []
            assert client.patch(f"/api/notes/{note.json()['id']}", json={"title": "hijack"}, headers=beta_headers).status_code == 404
            assert len(client.get("/api/notes", headers=alpha_headers).json()) == 1

            task = client.post("/api/tasks", json={"title": "Alpha task", "status": "backlog"}, headers=alpha_headers)
            assert task.status_code == 201, task.text
            assert client.get("/api/tasks", headers=beta_headers).json() == []
            assert client.get(f"/api/tasks/{task.json()['id']}", headers=beta_headers).status_code == 404

            debt = client.post("/api/tech-debt", json={
                "title": "Alpha debt", "scope": "src/app.ts", "repo_url": "https://github.com/example/repo",
                "description": "Hardcoded value.", "mitigation": "Read from config.", "current_state": "Still open.",
                "urgency": "medium", "impact": "Breaks deploys.",
            }, headers=alpha_headers)
            assert debt.status_code == 201, debt.text
            assert client.get("/api/tech-debt", headers=beta_headers).json() == []
            assert client.get(f"/api/tech-debt/{debt.json()['id']}", headers=beta_headers).status_code == 404
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()


def test_mcp_tools_forward_the_callers_credential(monkeypatch) -> None:
    """Every MCP tool must hand the caller's own key to the API, never the shared env token."""
    calls: list[tuple[str, str, str]] = []

    async def fake_api_request(method, path, payload=None, authorization=""):
        calls.append((method, path, authorization))
        if method == "GET":
            return []
        return {"id": "x", "title": "t", "repo_url": "r", "urgency": "low", "status": "open"}

    monkeypatch.setattr(mcp_server, "api_request", fake_api_request)
    monkeypatch.setattr(main.settings, "mcp_allowed_hosts", "updater.example.test")
    monkeypatch.setattr(main.settings, "updater_token", "server-token")

    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)
    # The MCP transport authorizes through the module-level SessionLocal, not the
    # FastAPI dependency override, so point it at the same throwaway database.
    monkeypatch.setattr(main, "SessionLocal", session_factory)

    def call_tool(client: TestClient, name: str, arguments: dict, key: str):
        response = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {key}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert not result.get("isError"), result["content"][0]["text"]
        return result

    client = _signed_in_client(test_engine, base_url="https://updater.example.test")
    try:
        with client:
            alpha = _register_account(client, "alpha@example.com")
            beta = _register_account(client, "beta@example.com")
            gamma = _register_account(client, "gamma@example.com")
            call_tool(client, "publish_feature", {
                "title": "T", "summary": "S", "repo_url": "https://github.com/a/b",
                "why": "W", "how_it_works": "H", "impact": "I", "files_changed": [], "tags": [],
            }, alpha)
            call_tool(client, "list_feature_updates", {"query": ""}, beta)
            call_tool(client, "report_tech_debt", {
                "title": "D", "scope": "s", "description": "d", "mitigation": "m", "impact": "i",
                "current_state": "open", "urgency": "low", "repo_url": "https://github.com/example/repo",
            }, gamma)
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()

    forwarded = [authorization for _, _, authorization in calls]
    assert forwarded == ["Bearer " + alpha, "Bearer " + beta, "Bearer " + gamma]


def test_mcp_list_tools_return_every_row(monkeypatch) -> None:
    """FastMCP truncates a raw list result to one element, so list tools wrap their rows."""
    rows = [
        {"id": str(index), "title": f"Feature {index}", "summary": "s", "repo_url": "https://github.com/example/repo", "shipped_at": "2026-09-30T00:00:00"}
        for index in range(3)
    ]

    async def fake_api_request(method, path, payload=None, authorization=""):
        return rows

    monkeypatch.setattr(mcp_server, "api_request", fake_api_request)
    monkeypatch.setattr(main.settings, "mcp_allowed_hosts", "updater.example.test")
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)
    monkeypatch.setattr(main, "SessionLocal", session_factory)
    client = _signed_in_client(test_engine, base_url="https://updater.example.test")
    try:
        with client:
            key = _register_account(client, "lister@example.com")
            listed = client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {key}"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_feature_updates", "arguments": {"query": ""}}},
            )
            assert listed.status_code == 200, listed.text
            result = listed.json()["result"]
            assert not result.get("isError"), result["content"][0]["text"]
            payload = json.loads(result["content"][0]["text"])
            assert isinstance(payload, dict), payload
            assert payload["count"] == 3
            assert {item["title"] for item in payload["updates"]} == {"Feature 0", "Feature 1", "Feature 2"}
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()


def test_backfill_adopts_unowned_rows_and_undo_is_precise(tmp_path, monkeypatch) -> None:
    """Staged adoption must keep every account's existing view, and undo only its own rows."""
    test_engine = create_engine(f"sqlite:///{tmp_path / 'backfill.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)
    monkeypatch.setattr(backfill_ownership, "SessionLocal", session_factory)
    monkeypatch.setattr(backfill_ownership, "engine", test_engine)

    def make_update(user_id, title, repo):
        return Update(user_id=user_id, title=title, summary="s" * 12, repo_url=repo,
                      why="w" * 12, how_it_works="h" * 12, impact="i" * 12, files_changed=[], tags=[])

    with session_factory() as db:
        alpha = User(email="alpha@example.com", password_hash=auth_utils.hash_password("correct horse battery"))
        beta = User(email="beta@example.com", password_hash=auth_utils.hash_password("correct horse battery"))
        db.add_all([alpha, beta])
        db.commit()
        db.refresh(alpha)
        db.refresh(beta)
        alpha_id = alpha.id
        beta_id = beta.id
        # Three rows the buggy server wrote with no owner, plus one genuinely owned by alpha.
        db.add_all([
            make_update(None, "Legacy A", "https://github.com/alpha/one"),
            make_update(None, "Legacy B", "https://github.com/alpha/two"),
            make_update(None, "Legacy other", "https://github.com/someone/three"),
            make_update(alpha_id, "Alpha own", "https://github.com/alpha/four"),
        ])
        db.add(Note(user_id=None, title="Legacy note"))
        db.commit()

    # Before adopting, both accounts see every unowned row: the fix changes nobody's view.
    with session_factory() as db:
        for owner in (None, alpha_id):
            seen = len(db.scalars(select(Update).where(main._ownership_clause(Update, owner))).all())
            assert seen == 4, seen

    # Adopt only alpha's two repos, leaving the unrelated row and the unowned note alone.
    run_id = "test-run"
    argv = ["--email", "alpha@example.com", "--repo", "github.com/alpha", "--run-id", run_id]
    monkeypatch.setattr("sys.argv", ["backfill", *argv])
    assert backfill_ownership.main() == 0

    with session_factory() as db:
        adopted = {u.title for u in db.scalars(select(Update).where(Update.user_id == alpha_id)).all()}
        assert adopted == {"Legacy A", "Legacy B", "Alpha own"}, adopted
        still_unowned = {u.title for u in db.scalars(select(Update).where(Update.user_id.is_(None))).all()}
        assert still_unowned == {"Legacy other"}, still_unowned
        # Beta's view is unchanged: the unrelated legacy row is still visible to it.
        beta_view = {u.title for u in db.scalars(select(Update).where(main._ownership_clause(Update, beta_id))).all()}
        assert beta_view == {"Legacy other"}, beta_view

    # Undo returns exactly the two adopted legacy rows, never alpha's pre-existing one.
    monkeypatch.setattr("sys.argv", ["backfill", "--undo", "--run-id", run_id])
    assert backfill_ownership.main() == 0
    with session_factory() as db:
        owned = {u.title for u in db.scalars(select(Update).where(Update.user_id == alpha_id)).all()}
        assert owned == {"Alpha own"}, owned
        unowned = {u.title for u in db.scalars(select(Update).where(Update.user_id.is_(None))).all()}
        assert unowned == {"Legacy A", "Legacy B", "Legacy other"}, unowned
    test_engine.dispose()
