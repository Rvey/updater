"""Workspaces, members, invites, projects and per-project scoping."""
import hashlib
import hmac as hmac_mod
import json
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth as auth_utils
from app import backfill_ownership, main, mcp_server
from app import workspaces as ws
from app.db import Base, Project, Task, Update, User, WorkspaceInvite, WorkspaceMember, now_utc
from test_api import _register_account, _signed_in_client


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Throwaway SQLite database wired into the app, lifespan migrations included."""
    test_engine = create_engine(f"sqlite:///{tmp_path / 'ws.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine)
    monkeypatch.setattr(main, "engine", test_engine)
    monkeypatch.setattr(main, "SessionLocal", factory)
    client = _signed_in_client(test_engine)
    with client:
        yield client, factory
    main.app.dependency_overrides.clear()
    test_engine.dispose()


def H(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def workspaces_of(client, key):
    response = client.get("/api/workspaces", headers=H(key))
    assert response.status_code == 200, response.text
    return response.json()


def debt_body(**extra):
    return {
        "title": "Some debt", "scope": "src/app.ts", "repo_url": "https://github.com/example/repo",
        "description": "Hardcoded value here.", "mitigation": "Read from config.", "current_state": "Still open.",
        "urgency": "medium", "impact": "Breaks deploys.", **extra,
    }


def update_body(**extra):
    return {
        "title": "Shipped thing", "summary": "A shipped change recorded for a project.",
        "repo_url": "https://github.com/example/repo", "why": "Each project keeps its own history.",
        "how_it_works": "The API stamps the project id.", "impact": "Teams share one history.", **extra,
    }


def test_register_creates_default_workspace_project_and_owner_membership(env) -> None:
    client, factory = env
    key = _register_account(client, "dana.smith@example.com")
    found = workspaces_of(client, key)
    assert len(found) == 1
    workspace = found[0]
    assert workspace["name"] == "dana.smith workspace" and workspace["role"] == "owner"
    assert [(p["name"], p["is_default"]) for p in workspace["projects"]] == [("General", True)]
    assert set(workspace["projects"][0]) == {"id", "name", "slug", "repo_url", "is_default"}
    with factory() as db:
        assert db.scalar(select(WorkspaceMember.role)) == "owner"


def test_workspace_and_project_crud(env) -> None:
    client, _ = env
    alpha = _register_account(client, "alpha@example.com")
    beta = _register_account(client, "beta@example.com")
    created = client.post("/api/workspaces", json={"name": "Team Rocket"}, headers=H(alpha))
    assert created.status_code == 201, created.text
    wid = created.json()["id"]
    assert created.json()["role"] == "owner" and created.json()["projects"][0]["is_default"] is True
    assert len(workspaces_of(client, alpha)) == 2

    assert client.patch(f"/api/workspaces/{wid}", json={"name": "Rocket"}, headers=H(alpha)).json()["name"] == "Rocket"
    assert client.patch(f"/api/workspaces/{wid}", json={"name": "x"}, headers=H(beta)).status_code == 404

    proj = client.post(f"/api/workspaces/{wid}/projects", json={"name": "Web App", "repo_url": "git@github.com:Example/Web.git"}, headers=H(alpha))
    assert proj.status_code == 201, proj.text
    pid = proj.json()["id"]
    assert proj.json()["repo_url"] == "https://github.com/example/web" and proj.json()["slug"] == "web-app"
    again = client.post(f"/api/workspaces/{wid}/projects", json={"name": "Web App"}, headers=H(alpha))
    assert again.json()["slug"] == "web-app-2"
    listed = client.get(f"/api/workspaces/{wid}/projects", headers=H(alpha)).json()
    assert [p["is_default"] for p in listed][0] is True and len(listed) == 3
    patched = client.patch(f"/api/projects/{pid}", json={"name": "Web", "repo_url": None}, headers=H(alpha))
    assert patched.json()["name"] == "Web" and patched.json()["repo_url"] is None

    # A project with content cannot be deleted; the default project never can.
    task = client.post("/api/tasks", json={"title": "t", "project_id": pid}, headers=H(alpha))
    assert task.status_code == 201
    assert client.delete(f"/api/projects/{pid}", headers=H(alpha)).status_code == 409
    default_id = listed[0]["id"]
    assert client.delete(f"/api/projects/{default_id}", headers=H(alpha)).status_code == 409
    assert client.delete(f"/api/tasks/{task.json()['id']}", headers=H(alpha)).status_code == 200
    assert client.delete(f"/api/projects/{pid}", headers=H(alpha)).status_code == 204
    assert client.delete(f"/api/projects/{pid}", headers=H(alpha)).status_code == 404

    # Delete workspace: owner only, never the last one.
    assert client.delete(f"/api/workspaces/{wid}", headers=H(beta)).status_code == 404
    assert client.delete(f"/api/workspaces/{wid}", headers=H(alpha)).status_code == 204
    only = workspaces_of(client, alpha)[0]["id"]
    assert client.delete(f"/api/workspaces/{only}", headers=H(alpha)).status_code == 409


def test_env_token_cannot_use_workspace_routes(env, monkeypatch) -> None:
    client, _ = env
    _register_account(client, "alpha@example.com")
    monkeypatch.setattr(main.settings, "updater_token", "shared-secret")
    assert client.get("/api/workspaces", headers=H("shared-secret")).status_code == 403
    assert client.get("/api/workspaces").status_code == 401


def test_invite_flow(env, monkeypatch) -> None:
    client, factory = env
    owner = _register_account(client, "owner@example.com")
    wid = workspaces_of(client, owner)[0]["id"]

    invite = client.post(f"/api/workspaces/{wid}/invites", json={"email": " New@Example.com ", "role": "member"}, headers=H(owner))
    assert invite.status_code == 201, invite.text
    body = invite.json()
    assert set(body) == {"id", "email", "role", "token", "expires_at"}
    assert body["email"] == "new@example.com" and body["token"].startswith("upi_")
    listed = client.get(f"/api/workspaces/{wid}/invites", headers=H(owner)).json()
    assert [i["email"] for i in listed] == ["new@example.com"] and "token" not in listed[0]
    # Re-inviting the same email re-issues: one open invite per (workspace, email).
    reissued = client.post(f"/api/workspaces/{wid}/invites", json={"email": "new@example.com"}, headers=H(owner)).json()
    assert reissued["token"] != body["token"]
    assert len(client.get(f"/api/workspaces/{wid}/invites", headers=H(owner)).json()) == 1

    stranger = _register_account(client, "stranger@example.com")
    assert client.post("/api/invites/accept", json={"token": reissued["token"]}, headers=H(stranger)).status_code == 403
    assert client.post("/api/invites/accept", json={"token": "upi_does-not-exist"}, headers=H(stranger)).status_code == 404
    # Only owners manage invites.
    assert client.post(f"/api/workspaces/{wid}/invites", json={"email": "x@example.com"}, headers=H(stranger)).status_code == 404

    newbie = _register_account(client, "new@example.com")
    assert client.post("/api/invites/accept", json={"token": body["token"]}, headers=H(newbie)).status_code == 404  # replaced
    accepted = client.post("/api/invites/accept", json={"token": reissued["token"]}, headers=H(newbie))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"workspace_id": wid, "role": "member"}
    assert client.post("/api/invites/accept", json={"token": reissued["token"]}, headers=H(newbie)).status_code == 410
    assert len(workspaces_of(client, newbie)) == 2
    # Accepted invites are no longer listed, and an existing member cannot be invited again.
    assert client.get(f"/api/workspaces/{wid}/invites", headers=H(owner)).json() == []
    assert client.post(f"/api/workspaces/{wid}/invites", json={"email": "new@example.com"}, headers=H(owner)).status_code == 409

    # Expired invites are rejected; revoked ones disappear.
    late = client.post(f"/api/workspaces/{wid}/invites", json={"email": "late@example.com"}, headers=H(owner)).json()
    late_user = _register_account(client, "late@example.com")
    with factory() as db:
        row = db.get(WorkspaceInvite, late["id"])
        row.expires_at = now_utc() - timedelta(minutes=1)
        db.commit()
    assert client.post("/api/invites/accept", json={"token": late["token"]}, headers=H(late_user)).status_code == 410
    assert client.get(f"/api/workspaces/{wid}/invites", headers=H(owner)).json() == []
    gone = client.post(f"/api/workspaces/{wid}/invites", json={"email": "gone@example.com"}, headers=H(owner)).json()
    assert client.delete(f"/api/workspaces/{wid}/invites/{gone['id']}", headers=H(owner)).status_code == 204
    assert client.delete(f"/api/workspaces/{wid}/invites/{gone['id']}", headers=H(owner)).status_code == 404


def test_members_add_roles_and_last_owner_protection(env) -> None:
    client, _ = env
    owner = _register_account(client, "owner@example.com")
    member = _register_account(client, "member@example.com")
    wid = workspaces_of(client, owner)[0]["id"]
    owner_id = client.get(f"/api/workspaces/{wid}/members", headers=H(owner)).json()[0]["user_id"]

    # An existing account is added directly; an unknown email becomes an invite.
    added = client.post(f"/api/workspaces/{wid}/members", json={"email": "Member@example.com", "role": "member"}, headers=H(owner))
    assert added.status_code == 201, added.text
    assert added.json()["status"] == "added" and added.json()["member"]["email"] == "member@example.com"
    member_id = added.json()["member"]["user_id"]
    assert client.post(f"/api/workspaces/{wid}/members", json={"email": "member@example.com"}, headers=H(owner)).status_code == 409
    invited = client.post(f"/api/workspaces/{wid}/members", json={"email": "ghost@example.com"}, headers=H(owner))
    assert invited.status_code == 201 and invited.json()["status"] == "invited" and invited.json()["invite"]["token"].startswith("upi_")
    assert client.post(f"/api/workspaces/{wid}/members", json={"email": "a@example.com", "role": "admin"}, headers=H(owner)).status_code == 422

    listed = client.get(f"/api/workspaces/{wid}/members", headers=H(member)).json()
    assert [(m["email"], m["role"]) for m in listed] == [("owner@example.com", "owner"), ("member@example.com", "member")]
    assert set(listed[0]) == {"user_id", "email", "role", "created_at"}

    # Members can read but not manage.
    assert client.post(f"/api/workspaces/{wid}/members", json={"email": "x@example.com"}, headers=H(member)).status_code == 403
    assert client.patch(f"/api/workspaces/{wid}/members/{owner_id}", json={"role": "member"}, headers=H(member)).status_code == 403
    assert client.delete(f"/api/workspaces/{wid}/members/{owner_id}", headers=H(member)).status_code == 403

    # The last owner can be neither demoted nor removed.
    assert client.patch(f"/api/workspaces/{wid}/members/{owner_id}", json={"role": "member"}, headers=H(owner)).status_code == 409
    assert client.delete(f"/api/workspaces/{wid}/members/{owner_id}", headers=H(owner)).status_code == 409
    promoted = client.patch(f"/api/workspaces/{wid}/members/{member_id}", json={"role": "owner"}, headers=H(owner))
    assert promoted.status_code == 200 and promoted.json()["role"] == "owner"
    assert client.patch(f"/api/workspaces/{wid}/members/{owner_id}", json={"role": "member"}, headers=H(owner)).status_code == 200
    assert client.delete(f"/api/workspaces/{wid}/members/{member_id}", headers=H(owner)).status_code == 403  # demoted: no longer owner
    # A member may remove themselves; the new sole owner may not.
    assert client.delete(f"/api/workspaces/{wid}/members/{owner_id}", headers=H(owner)).status_code == 204
    assert client.delete(f"/api/workspaces/{wid}/members/{member_id}", headers=H(member)).status_code == 409
    assert client.get(f"/api/workspaces/{wid}/members", headers=H(owner)).status_code == 404  # no longer a member
    assert client.delete(f"/api/workspaces/{wid}/members/{owner_id}", headers=H(member)).status_code == 404


def test_non_members_get_404_on_every_project_scoped_route(env) -> None:
    client, _ = env
    alpha = _register_account(client, "alpha@example.com")
    beta = _register_account(client, "beta@example.com")
    wid = workspaces_of(client, alpha)[0]["id"]
    pid = workspaces_of(client, alpha)[0]["projects"][0]["id"]
    note = client.post("/api/notes", json={"title": "n", "project_id": pid}, headers=H(alpha)).json()["id"]
    task = client.post("/api/tasks", json={"title": "t", "project_id": pid}, headers=H(alpha)).json()["id"]
    debt = client.post("/api/tech-debt", json=debt_body(project_id=pid), headers=H(alpha)).json()["id"]
    upd = client.post("/api/updates", json=update_body(project_id=pid), headers=H(alpha)).json()["id"]
    b = H(beta)

    for path in (f"/api/workspaces/{wid}/members", f"/api/workspaces/{wid}/invites", f"/api/workspaces/{wid}/projects"):
        assert client.get(path, headers=b).status_code == 404, path
    assert client.post(f"/api/workspaces/{wid}/projects", json={"name": "x"}, headers=b).status_code == 404
    assert client.post(f"/api/workspaces/{wid}/members", json={"email": "z@example.com"}, headers=b).status_code == 404
    assert client.patch(f"/api/projects/{pid}", json={"name": "x"}, headers=b).status_code == 404
    assert client.delete(f"/api/projects/{pid}", headers=b).status_code == 404
    assert client.delete(f"/api/workspaces/{wid}", headers=b).status_code == 404

    # Naming a foreign project is a 404, on reads and on writes.
    for path in ("/api/tasks", "/api/notes", "/api/tech-debt", "/api/updates", "/api/github/links"):
        assert client.get(path, params={"project_id": pid}, headers=b).status_code == 404, path
    assert client.post("/api/tasks", json={"title": "t", "project_id": pid}, headers=b).status_code == 404
    assert client.post("/api/notes", json={"title": "n", "project_id": pid}, headers=b).status_code == 404
    assert client.post("/api/tech-debt", json=debt_body(project_id=pid), headers=b).status_code == 404
    assert client.post("/api/updates", json=update_body(project_id=pid), headers=b).status_code == 404
    assert client.post("/api/github/sync", json={"repo": "o/r", "project_id": pid}, headers=b).status_code == 404
    assert client.post("/api/github/links", json={"repo": "o/r", "project_id": pid}, headers=b).status_code == 404
    assert client.post("/api/tasks/reorder", json={"columns": {"backlog": [task]}, "project_id": pid}, headers=b).status_code == 404

    # Foreign ids by row.
    assert client.get(f"/api/tasks/{task}", headers=b).status_code == 404
    assert client.patch(f"/api/tasks/{task}", json={"title": "x"}, headers=b).status_code == 404
    assert client.delete(f"/api/tasks/{task}", headers=b).status_code == 404
    assert client.patch(f"/api/notes/{note}", json={"title": "x"}, headers=b).status_code == 404
    assert client.delete(f"/api/notes/{note}", headers=b).status_code == 404
    assert client.get(f"/api/tech-debt/{debt}", headers=b).status_code == 404
    assert client.patch(f"/api/tech-debt/{debt}", json={"status": "resolved"}, headers=b).status_code == 404
    assert client.delete(f"/api/tech-debt/{debt}", headers=b).status_code == 404
    assert client.get(f"/api/updates/{upd}", headers=b).status_code == 404
    assert client.post(f"/api/updates/{upd}/impact-notes", json={"note": "nope nope"}, headers=b).status_code == 404
    assert client.post("/api/tasks/reorder", json={"columns": {"backlog": [task]}}, headers=b).status_code == 404
    for path in ("/api/tasks", "/api/notes", "/api/tech-debt", "/api/updates", "/api/github/links"):
        assert client.get(path, headers=b).json() == [], path


def test_per_project_isolation_and_defaults(env) -> None:
    client, _ = env
    alpha = _register_account(client, "alpha@example.com")
    beta = _register_account(client, "beta@example.com")
    wid = workspaces_of(client, alpha)[0]["id"]
    general = workspaces_of(client, alpha)[0]["projects"][0]["id"]
    other = client.post(f"/api/workspaces/{wid}/projects", json={"name": "Other", "repo_url": "https://github.com/example/other"}, headers=H(alpha)).json()["id"]
    a = H(alpha)

    # Create without project_id -> default project; with repo_url match -> the matching project.
    t_default = client.post("/api/tasks", json={"title": "default task"}, headers=a).json()
    assert t_default["project_id"] == general
    t_matched = client.post("/api/tasks", json={"title": "matched", "repo_url": "https://github.com/Example/Other.git"}, headers=a).json()
    assert t_matched["project_id"] == other
    t_explicit = client.post("/api/tasks", json={"title": "explicit", "project_id": other}, headers=a).json()
    assert t_explicit["project_id"] == other
    n_default = client.post("/api/notes", json={"title": "n"}, headers=a).json()
    assert n_default["project_id"] == general
    n_other = client.post("/api/notes", json={"title": "n2", "project_id": other}, headers=a).json()
    d_default = client.post("/api/tech-debt", json=debt_body(), headers=a).json()
    assert d_default["project_id"] == general
    d_other = client.post("/api/tech-debt", json=debt_body(title="Other debt", repo_url="https://github.com/example/other"), headers=a).json()
    assert d_other["project_id"] == other  # repo_url matched the project
    u_default = client.post("/api/updates", json=update_body(external_id="example/repo:a"), headers=a).json()
    assert u_default["project_id"] == general
    u_other = client.post("/api/updates", json=update_body(external_id="example/repo:b", project_id=other), headers=a).json()
    assert u_other["project_id"] == other

    def ids(path, **params):
        response = client.get(path, params=params, headers=a)
        assert response.status_code == 200, response.text
        return {row["id"] for row in response.json()}

    # No project_id -> union; project_id -> exactly that project; slug works too.
    assert ids("/api/tasks") == {t_default["id"], t_matched["id"], t_explicit["id"]}
    assert ids("/api/tasks", project_id=general) == {t_default["id"]}
    assert ids("/api/tasks", project_id=other) == {t_matched["id"], t_explicit["id"]}
    assert ids("/api/tasks", project_id="other") == {t_matched["id"], t_explicit["id"]}
    assert ids("/api/notes", project_id=general) == {n_default["id"]} and ids("/api/notes", project_id=other) == {n_other["id"]}
    assert ids("/api/tech-debt", project_id=other) == {d_other["id"]} and len(ids("/api/tech-debt")) == 2
    assert ids("/api/updates", project_id=general) == {u_default["id"]} and ids("/api/updates", project_id=other) == {u_other["id"]}
    assert len(ids("/api/updates")) == 2

    # Positions are per project and per column.
    positions = {t["title"]: t["position"] for t in client.get("/api/tasks", headers=a).json()}
    assert positions == {"default task": 0, "matched": 0, "explicit": 1}

    # Moving into a project the caller does not belong to is a 404; into one they do, a move.
    beta_project = workspaces_of(client, beta)[0]["projects"][0]["id"]
    assert client.patch(f"/api/tasks/{t_default['id']}", json={"project_id": beta_project}, headers=a).status_code == 404
    assert client.patch(f"/api/notes/{n_default['id']}", json={"project_id": beta_project}, headers=a).status_code == 404
    assert client.patch(f"/api/tech-debt/{d_default['id']}", json={"project_id": beta_project}, headers=a).status_code == 404
    moved = client.patch(f"/api/tasks/{t_default['id']}", json={"project_id": other}, headers=a)
    assert moved.status_code == 200 and moved.json()["project_id"] == other and moved.json()["position"] == 2
    assert client.patch(f"/api/notes/{n_default['id']}", json={"project_id": other}, headers=a).json()["project_id"] == other
    assert client.patch(f"/api/tech-debt/{d_default['id']}", json={"project_id": other}, headers=a).json()["project_id"] == other
    assert ids("/api/tasks", project_id=general) == set()

    # Reorder and delete re-pack each project independently.
    in_other = [t["id"] for t in client.get("/api/tasks", params={"project_id": other}, headers=a).json()]
    solo = client.post("/api/tasks", json={"title": "solo", "project_id": general}, headers=a).json()
    reordered = client.post("/api/tasks/reorder", json={"columns": {"backlog": list(reversed(in_other))}, "project_id": other}, headers=a)
    assert reordered.status_code == 200, reordered.text
    assert [t["id"] for t in reordered.json()] == list(reversed(in_other))
    assert client.get(f"/api/tasks/{solo['id']}", headers=a).json()["position"] == 0
    assert client.delete(f"/api/tasks/{in_other[0]}", headers=a).status_code == 200
    assert [t["position"] for t in client.get("/api/tasks", params={"project_id": other}, headers=a).json()] == [0, 1]
    assert client.get(f"/api/tasks/{solo['id']}", headers=a).json()["position"] == 0

    # Teammates in the workspace share the data; outsiders still see nothing.
    client.post(f"/api/workspaces/{wid}/members", json={"email": "beta@example.com"}, headers=a)
    assert len(client.get("/api/tasks", params={"project_id": other}, headers=H(beta)).json()) == 2
    mine = client.post("/api/tasks", json={"title": "beta wrote", "project_id": other}, headers=H(beta)).json()
    assert ids("/api/tasks", project_id=other) >= {mine["id"]}
    # Beta's own default (first workspace) is unaffected by the membership: still its own project.
    assert client.post("/api/tasks", json={"title": "beta default"}, headers=H(beta)).json()["project_id"] == beta_project


def test_republish_stays_inside_the_project_boundary(env) -> None:
    client, _ = env
    alpha = _register_account(client, "alpha@example.com")
    beta = _register_account(client, "beta@example.com")
    first = client.post("/api/updates", json=update_body(external_id="example/repo:x"), headers=H(alpha))
    assert first.status_code == 201
    again = client.post("/api/updates", json=update_body(external_id="example/repo:x", commit_sha="abc"), headers=H(alpha))
    assert again.json()["id"] == first.json()["id"] and again.json()["commit_sha"] == "abc"
    assert client.post("/api/updates", json=update_body(external_id="example/repo:x"), headers=H(beta)).status_code == 409


def test_context_requests_follow_project_membership(env) -> None:
    client, _ = env
    alpha = _register_account(client, "alpha@example.com")
    beta = _register_account(client, "beta@example.com")
    upd = client.post("/api/updates", json=update_body(), headers=H(alpha)).json()["id"]
    request = client.post(f"/api/updates/{upd}/context-requests", json={"question": "Where is it?"}, headers=H(alpha))
    assert request.status_code == 201
    assert len(client.get("/api/context-requests", headers=H(alpha)).json()) == 1
    assert client.get("/api/context-requests", headers=H(beta)).json() == []


def test_env_token_and_open_preview_still_see_everything(env, monkeypatch) -> None:
    client, factory = env
    alpha = _register_account(client, "alpha@example.com")
    beta = _register_account(client, "beta@example.com")
    ta = client.post("/api/tasks", json={"title": "alpha"}, headers=H(alpha)).json()
    tb = client.post("/api/tasks", json={"title": "beta"}, headers=H(beta)).json()
    assert ta["project_id"] != tb["project_id"]
    monkeypatch.setattr(main.settings, "updater_token", "shared-secret")
    shared = H("shared-secret")
    assert {t["id"] for t in client.get("/api/tasks", headers=shared).json()} == {ta["id"], tb["id"]}
    assert client.get(f"/api/tasks/{ta['id']}", headers=shared).status_code == 200
    legacy = client.post("/api/tasks", json={"title": "legacy"}, headers=shared).json()
    assert legacy["project_id"] is None
    only_a = client.get("/api/tasks", params={"project_id": ta["project_id"]}, headers=shared).json()
    assert [t["id"] for t in only_a] == [ta["id"]]
    assert legacy["id"] not in {t["id"] for t in client.get("/api/tasks", headers=H(alpha)).json()}
    # Open preview: no env token and no users means nothing to scope by.
    with factory() as db:
        for user in db.scalars(select(User)).all():
            db.delete(user)
        db.commit()
    monkeypatch.setattr(main.settings, "updater_token", "")
    assert len(client.get("/api/tasks").json()) == 3


def test_github_links_and_webhook_fan_out_by_project(env, monkeypatch) -> None:
    from test_github_items import CID, SECRET, Upstream
    from app import affinebot_client as ab

    client, _ = env
    monkeypatch.setattr(main.settings, "github_webhook_secret", "whsec")
    fake = Upstream()
    fake.items = [{**fake.items[0], "title": "Bug"}]
    monkeypatch.setattr(ab, "_transport_override", httpx.MockTransport(fake))
    ab._cache.clear()
    alpha = _register_account(client, "alpha@example.com")
    beta = _register_account(client, "beta@example.com")
    pa = workspaces_of(client, alpha)[0]["projects"][0]["id"]
    pb = workspaces_of(client, beta)[0]["projects"][0]["id"]
    for key in (alpha, beta):
        wid = workspaces_of(client, key)[0]["id"]
        put = client.put(f"/api/workspaces/{wid}/affinebot", headers=H(key),
                         json={"base_url": "https://bot.example.com", "client_id": CID, "secret": SECRET})
        assert put.status_code == 200, put.text
    la = client.post("/api/github/links", json={"repo": "o/r", "project_id": pa}, headers=H(alpha))
    assert la.status_code == 201 and la.json()["project_id"] == pa
    assert client.post("/api/github/links", json={"repo": "o/r", "project_id": pa}, headers=H(alpha)).json()["id"] == la.json()["id"]
    lb = client.post("/api/github/links", json={"repo": "o/r", "project_id": pb}, headers=H(beta))
    assert lb.json()["id"] != la.json()["id"] and lb.json()["project_id"] == pb
    assert [l["id"] for l in client.get("/api/github/links", headers=H(alpha)).json()] == [la.json()["id"]]
    assert client.delete(f"/api/github/links/{la.json()['id']}", headers=H(beta)).status_code == 404

    sync = client.post("/api/github/sync", json={"repo": "o/r", "project_id": pa}, headers=H(alpha))
    assert sync.json()["created"] == 0 and sync.json()["updated"] == 1  # the link's initial sync already imported it
    assert len(client.get("/api/tasks", params={"project_id": pa}, headers=H(alpha)).json()) == 1

    issue = {"number": 7, "title": "Crash", "body": "", "state": "open", "html_url": "https://github.com/o/r/issues/7", "labels": []}
    raw = json.dumps({"action": "opened", "repository": {"full_name": "o/r"}, "issue": issue}).encode()
    sig = "sha256=" + hmac_mod.new(b"whsec", raw, hashlib.sha256).hexdigest()
    hook = client.post("/api/github/webhook", content=raw, headers={"x-github-event": "issues", "x-hub-signature-256": sig, "content-type": "application/json"})
    assert hook.json()["linked"] == 2
    assert {t["external_id"] for t in client.get("/api/tasks", headers=H(beta)).json()} == {"github:o/r#1", "github:o/r#7"}
    assert {t["external_id"] for t in client.get("/api/tasks", headers=H(alpha)).json()} == {"github:o/r#1", "github:o/r#7"}


LEGACY_SCHEMA = """
CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, email VARCHAR(320) UNIQUE, password_hash VARCHAR(256), created_at DATETIME);
CREATE TABLE updates (id VARCHAR(36) PRIMARY KEY, external_id VARCHAR(255) UNIQUE, title VARCHAR(180), summary TEXT, repo_url VARCHAR(600),
  branch VARCHAR(255), commit_sha VARCHAR(80), pr_url VARCHAR(600), author_agent VARCHAR(100), why TEXT, how_it_works TEXT, impact TEXT,
  tradeoffs TEXT, learning_notes TEXT, files_changed JSON, tags JSON, shipped_at DATETIME, created_at DATETIME, code_context JSON, user_id VARCHAR(36));
CREATE TABLE notes (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36), title VARCHAR(180), content TEXT, color VARCHAR(20), created_at DATETIME, updated_at DATETIME);
CREATE TABLE tasks (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36), title VARCHAR(180), description TEXT, status VARCHAR(20), priority VARCHAR(20),
  position INTEGER, repo_url VARCHAR(600), branch VARCHAR(255), tags JSON, assignee VARCHAR(120), due_date DATETIME, author_agent VARCHAR(100),
  external_id VARCHAR(255), external_url VARCHAR(600), created_at DATETIME, updated_at DATETIME, completed_at DATETIME);
CREATE TABLE tech_debt (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36), title VARCHAR(180), scope VARCHAR(300), description TEXT, impact TEXT,
  mitigation TEXT, current_state TEXT, urgency VARCHAR(20), status VARCHAR(20), repo_url VARCHAR(600), file_path VARCHAR(600), files JSON, tags JSON,
  branch VARCHAR(255), commit_sha VARCHAR(80), author_agent VARCHAR(100), created_at DATETIME, updated_at DATETIME, resolved_at DATETIME);
CREATE TABLE github_repo_links (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36), repo VARCHAR(300), created_at DATETIME, last_event_at DATETIME,
  UNIQUE (user_id, repo));
"""


def _legacy_db(tmp_path, monkeypatch):
    legacy = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}", connect_args={"check_same_thread": False})
    with legacy.begin() as c:
        for statement in LEGACY_SCHEMA.strip().split(";\n"):
            if statement.strip():
                c.execute(text(statement))
        pw = auth_utils.hash_password("correct horse battery")
        for uid, email, created in (("u-alice", "alice@example.com", "2026-01-01"), ("u-bob", "bob@example.com", "2026-02-01")):
            c.execute(text("INSERT INTO users VALUES (:i, :e, :p, :c)"), {"i": uid, "e": email, "p": pw, "c": created})
        task = "INSERT INTO tasks (id, user_id, title, description, status, priority, position, tags, repo_url, created_at, updated_at) VALUES (:i, :u, :t, '', 'backlog', 'medium', 0, '[]', :r, '2026-03-01', '2026-03-01')"
        c.execute(text(task), {"i": "t-alice", "u": "u-alice", "t": "alice task", "r": None})
        c.execute(text(task), {"i": "t-bob", "u": "u-bob", "t": "bob task", "r": None})
        c.execute(text(task), {"i": "t-legacy", "u": None, "t": "legacy task", "r": None})
        c.execute(text("INSERT INTO notes (id, user_id, title, content, color, created_at, updated_at) VALUES ('n-bob', 'u-bob', 'bob note', '', 'default', '2026-03-01', '2026-03-01')"))
        c.execute(text("INSERT INTO github_repo_links (id, user_id, repo, created_at) VALUES ('l-bob', 'u-bob', 'o/r', '2026-03-01')"))
    monkeypatch.setattr(main, "engine", legacy)
    monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=legacy))
    return legacy


def test_legacy_database_migrates_and_is_idempotent(tmp_path, monkeypatch) -> None:
    from sqlalchemy import inspect

    legacy = _legacy_db(tmp_path, monkeypatch)
    client = _signed_in_client(legacy)
    try:
        with client:
            for table in ("updates", "tasks", "notes", "tech_debt", "github_repo_links"):
                assert "project_id" in {c["name"] for c in inspect(legacy).get_columns(table)}, table
            index_names = {i["name"] for t in ("tasks", "github_repo_links") for i in inspect(legacy).get_indexes(t)}
            assert {"uq_tasks_project_external", "uq_github_repo_links_project_repo", "ix_tasks_project_id"} <= index_names

            def snapshot():
                with legacy.connect() as c:
                    return (
                        c.execute(text("SELECT id, project_id FROM tasks ORDER BY id")).all(),
                        c.execute(text("SELECT id, project_id FROM notes ORDER BY id")).all(),
                        c.execute(text("SELECT id, project_id FROM github_repo_links ORDER BY id")).all(),
                        c.execute(text("SELECT count(*) FROM workspaces")).scalar(),
                        c.execute(text("SELECT count(*) FROM projects")).scalar(),
                        c.execute(text("SELECT count(*) FROM workspace_members")).scalar(),
                    )

            first = snapshot()
            tasks, notes, links, n_ws, n_proj, n_members = first
            assert (n_ws, n_proj, n_members) == (2, 2, 2)
            assert all(project for _, project in tasks)  # owned rows AND the legacy NULL-owner row are adopted
            assert notes[0][1] and links[0][1]

            # Re-running every migration step changes nothing.
            main._ensure_project_columns()
            with main.SessionLocal() as db:
                ws.ensure_default_workspaces(db)
            assert snapshot() == first

            login = lambda e: client.post("/api/auth/login", json={"email": e, "password": "correct horse battery"}).json()["session_token"]
            alice, bob = login("alice@example.com"), login("bob@example.com")
            alice_tasks = {t["title"] for t in client.get("/api/tasks", headers=H(alice)).json()}
            bob_tasks = {t["title"] for t in client.get("/api/tasks", headers=H(bob)).json()}
            # The first registered account adopts the unowned legacy row; the other account never sees it.
            assert alice_tasks == {"alice task", "legacy task"}
            assert bob_tasks == {"bob task"}
            assert [n["title"] for n in client.get("/api/notes", headers=H(bob)).json()] == ["bob note"]
            assert client.get("/api/notes", headers=H(alice)).json() == []
            assert [l["repo"] for l in client.get("/api/github/links", headers=H(bob)).json()] == ["o/r"]

            # The env token keeps seeing every row, including the unowned one.
            monkeypatch.setattr(main.settings, "updater_token", "shared-secret")
            assert len(client.get("/api/tasks", headers=H("shared-secret")).json()) == 3
            monkeypatch.setattr(main.settings, "updater_token", "")
    finally:
        main.app.dependency_overrides.clear()
        legacy.dispose()


def test_default_workspace_prefers_project_matching_repo(env) -> None:
    client, factory = env
    key = _register_account(client, "alpha@example.com")
    wid = workspaces_of(client, key)[0]["id"]
    web = client.post(f"/api/workspaces/{wid}/projects", json={"name": "Web", "repo_url": "https://github.com/example/web"}, headers=H(key)).json()["id"]
    with factory() as db:
        user = db.scalar(select(User))
        db.add(Task(user_id=user.id, title="legacy web", repo_url="git@github.com:Example/web.git"))
        db.add(Task(user_id=user.id, title="legacy plain"))
        db.commit()
        ws.ensure_default_workspaces(db)
        by_title = {t.title: t.project_id for t in db.scalars(select(Task)).all()}
        default = ws.default_project_for(db, user.id).id
    assert by_title == {"legacy web": web, "legacy plain": default}


def test_backfill_project_flag_and_undo(tmp_path, monkeypatch) -> None:
    test_engine = create_engine(f"sqlite:///{tmp_path / 'bf.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine)
    monkeypatch.setattr(backfill_ownership, "SessionLocal", factory)
    monkeypatch.setattr(backfill_ownership, "engine", test_engine)
    with factory() as db:
        user = User(email="alpha@example.com", password_hash="x")
        db.add(user)
        db.flush()
        workspace = ws.create_default_workspace(db, user)
        extra = Project(workspace_id=workspace.id, name="Extra", slug="extra")
        db.add(extra)
        db.add(Task(title="legacy"))
        db.commit()
        user_id, extra_id = user.id, extra.id
    monkeypatch.setattr("sys.argv", ["backfill", "--email", "alpha@example.com", "--project", "extra", "--run-id", "r1"])
    assert backfill_ownership.main() == 0
    with factory() as db:
        task = db.scalar(select(Task))
        assert (task.user_id, task.project_id) == (user_id, extra_id)
    monkeypatch.setattr("sys.argv", ["backfill", "--undo", "--run-id", "r1"])
    assert backfill_ownership.main() == 0
    with factory() as db:
        task = db.scalar(select(Task))
        assert (task.user_id, task.project_id) == (None, None)
    monkeypatch.setattr("sys.argv", ["backfill", "--email", "alpha@example.com", "--project", "nope"])
    with pytest.raises(SystemExit):
        backfill_ownership.main()
    test_engine.dispose()


def test_mcp_project_argument_and_list_projects(monkeypatch) -> None:
    calls: list[tuple[str, str, object, str]] = []

    async def fake_api_request(method, path, payload=None, authorization=""):
        calls.append((method, path, payload, authorization))
        if path == "/api/workspaces":
            return [{"id": "w1", "name": "Team", "slug": "team", "role": "owner",
                     "projects": [{"id": "p1", "name": "General", "slug": "general", "repo_url": None, "is_default": True}]}]
        if method == "GET":
            return []
        return {"id": "x", "title": "t", "repo_url": "r", "urgency": "low", "status": "open"}

    monkeypatch.setattr(mcp_server, "api_request", fake_api_request)
    monkeypatch.setattr(main.settings, "mcp_allowed_hosts", "updater.example.test")
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine)
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main, "engine", test_engine)
    client = _signed_in_client(test_engine, base_url="https://updater.example.test")

    def call_tool(name, arguments, key):
        response = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {key}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert not result.get("isError"), result["content"][0]["text"]
        return result

    try:
        with client:
            key = _register_account(client, "alpha@example.com")
            listed = call_tool("list_projects", {}, key)
            payload = json.loads(listed["content"][0]["text"])
            assert payload["count"] == 1 and payload["projects"][0]["slug"] == "general" and payload["projects"][0]["workspace"] == "Team"
            call_tool("publish_feature", {
                "title": "T", "summary": "S", "repo_url": "https://github.com/a/b", "why": "W", "how_it_works": "H",
                "impact": "I", "files_changed": [], "tags": [], "project": "general",
            }, key)
            call_tool("list_feature_updates", {"query": "q", "project": "p1"}, key)
            call_tool("report_tech_debt", {
                "title": "D", "scope": "s", "description": "d", "mitigation": "m", "impact": "i",
                "current_state": "open", "urgency": "low", "repo_url": "https://github.com/a/b", "project": "general",
            }, key)
            call_tool("list_tech_debt", {"project": "p1"}, key)
    finally:
        main.app.dependency_overrides.clear()
        test_engine.dispose()

    by_path = {(m, p.split("?")[0]): (pl, a, p) for m, p, pl, a in calls}
    assert all(a == "Bearer " + key for *_, a in calls)
    assert by_path[("POST", "/api/updates")][0]["project_id"] == "general"
    assert by_path[("POST", "/api/tech-debt")][0]["project_id"] == "general"
    assert "project_id=p1" in by_path[("GET", "/api/updates")][2]
    assert "project_id=p1" in by_path[("GET", "/api/tech-debt")][2]
