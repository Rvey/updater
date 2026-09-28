from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import main
from app.db import Base


def _client(tmp_path):
    test_engine = create_engine(f"sqlite:///{tmp_path / "auth.sqlite3"}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(bind=test_engine)

    def test_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = test_db
    return test_engine


def test_register_login_keys_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "updater_token", "")
    monkeypatch.setattr(main.settings, "mcp_allowed_hosts", "auth.example.test")
    engine = _client(tmp_path)
    try:
        with TestClient(main.app, base_url="https://auth.example.test") as client:
            reg = client.post("/api/auth/register", json={"email": "Ada@Example.com", "password": "correct-horse-42"})
            assert reg.status_code == 201, reg.text
            session_token = reg.json()["session_token"]
            assert session_token.startswith("ups_")
            assert reg.json()["email"] == "ada@example.com"

            dup = client.post("/api/auth/register", json={"email": "ada@example.com", "password": "other-password-1"})
            assert dup.status_code == 409

            bad = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "nope-nope-nope"})
            assert bad.status_code == 401

            login = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "correct-horse-42"})
            assert login.status_code == 200, login.text
            user_headers = {"Authorization": "Bearer " + login.json()["session_token"]}

            me = client.get("/api/auth/me", headers=user_headers)
            assert me.status_code == 200
            assert me.json() == {"email": "ada@example.com", "legacy": False}

            updates = client.get("/api/updates", headers=user_headers)
            assert updates.status_code == 200

            created = client.post("/api/auth/keys", json={"name": "ci agent"}, headers=user_headers)
            assert created.status_code == 201, created.text
            api_key = created.json()["key"]
            assert api_key.startswith("upk_")
            key_id = created.json()["id"]
            key_headers = {"Authorization": "Bearer " + api_key}

            listed = client.get("/api/auth/keys", headers=user_headers)
            assert listed.status_code == 200
            assert [k["id"] for k in listed.json()] == [key_id]

            with_key = client.get("/api/updates", headers=key_headers)
            assert with_key.status_code == 200

            mcp = client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream", "Authorization": "Bearer " + api_key},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "auth-test", "version": "1"},
                }},
            )
            assert mcp.status_code == 200, mcp.text

            revoked = client.delete(f"/api/auth/keys/{key_id}", headers=user_headers)
            assert revoked.status_code == 200, revoked.text
            assert client.get("/api/updates", headers=key_headers).status_code == 401
            after = client.get("/api/auth/keys", headers=user_headers).json()
            assert after[0]["revoked_at"] is not None
            assert after[0]["last_used_at"] is not None

            assert client.post("/api/auth/logout", headers=user_headers).status_code == 200
            assert client.get("/api/updates", headers=user_headers).status_code == 401
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()


def test_change_password_and_email(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "updater_token", "")
    monkeypatch.setattr(main.settings, "mcp_allowed_hosts", "auth.example.test")
    engine = _client(tmp_path)
    try:
        with TestClient(main.app, base_url="https://auth.example.test") as client:
            reg = client.post("/api/auth/register", json={"email": "ada@example.com", "password": "correct-horse-42"})
            assert reg.status_code == 201, reg.text
            headers = {"Authorization": "Bearer " + reg.json()["session_token"]}

            wrong = client.patch(
                "/api/auth/account",
                json={"current_password": "nope-nope-nope", "new_password": "another-horse-43"},
                headers=headers,
            )
            assert wrong.status_code == 401

            short = client.patch(
                "/api/auth/account",
                json={"current_password": "correct-horse-42", "new_password": "short"},
                headers=headers,
            )
            assert short.status_code == 422

            same = client.patch(
                "/api/auth/account",
                json={"current_password": "correct-horse-42", "new_password": "correct-horse-42"},
                headers=headers,
            )
            assert same.status_code == 422

            nothing = client.patch("/api/auth/account", json={"current_password": "correct-horse-42"}, headers=headers)
            assert nothing.status_code == 422

            # a second device session must be revoked by the password change
            second = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "correct-horse-42"})
            second_headers = {"Authorization": "Bearer " + second.json()["session_token"]}

            changed = client.patch(
                "/api/auth/account",
                json={
                    "email": "Grace@Example.com",
                    "current_password": "correct-horse-42",
                    "new_password": "new-horse-43",
                },
                headers=headers,
            )
            assert changed.status_code == 200, changed.text
            assert changed.json()["email"] == "grace@example.com"
            assert changed.json()["email_changed"] is True
            assert changed.json()["password_changed"] is True
            assert changed.json()["sessions_revoked"] == 1

            # current session stays signed in; the other device is signed out
            assert client.get("/api/auth/me", headers=headers).json()["email"] == "grace@example.com"
            assert client.get("/api/updates", headers=second_headers).status_code == 401

            # old password stops working, new one works
            assert client.post("/api/auth/login", json={"email": "grace@example.com", "password": "correct-horse-42"}).status_code == 401
            relogin = client.post("/api/auth/login", json={"email": "grace@example.com", "password": "new-horse-43"})
            assert relogin.status_code == 200

            # API keys can update the account too; all login sessions are revoked
            key = client.post("/api/auth/keys", json={"name": "agent"}, headers=headers)
            key_headers = {"Authorization": "Bearer " + key.json()["key"]}
            by_key = client.patch(
                "/api/auth/account",
                json={"current_password": "new-horse-43", "new_password": "key-horse-44"},
                headers=key_headers,
            )
            assert by_key.status_code == 200, by_key.text
            assert by_key.json()["password_changed"] is True
            assert client.get("/api/auth/me", headers=headers).status_code == 401
            assert client.post("/api/auth/login", json={"email": "grace@example.com", "password": "key-horse-44"}).status_code == 200
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()


def test_legacy_env_token_still_works(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "updater_token", "legacy-secret")
    engine = _client(tmp_path)
    try:
        with TestClient(main.app) as client:
            assert client.get("/api/updates").status_code == 401
            legacy = {"Authorization": "Bearer legacy-secret"}
            assert client.get("/api/updates", headers=legacy).status_code == 200
            assert client.get("/api/auth/me", headers=legacy).json() == {"email": None, "legacy": True}
            assert client.post("/api/auth/keys", json={"name": "x"}, headers=legacy).status_code == 403
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
