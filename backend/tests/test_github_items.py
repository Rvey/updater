"""GitHub repos/items/sync/links sourced through Affinebot (MockTransport; no GitHub, no PAT)."""
import hashlib
import hmac as hmac_mod
import json

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import affinebot_client as ab
from app import main
from app.db import Base, GitHubRepoLink
from test_api import _register_account, _signed_in_client
from test_workspaces import H, workspaces_of

SECRET = "abl_supersecretvalue123"
CID = "22222222-2222-2222-2222-222222222222"
HEALTH = {"ok": True, "app": "affinebot", "version": "1", "github_app": True, "redis": True, "db": True,
          "client": {"client_id": CID, "owner": "o", "installation_id": 7}}


def item(number, title="T", is_pr=False, state="open", **extra):
    return {"number": number, "title": title, "body": "", "state": state, "merged": False, "draft": False,
            "url": f"https://github.com/o/r/{'pull' if is_pr else 'issues'}/{number}", "author": "x",
            "assignees": [], "labels": [], "comments": 0, "is_pr": is_pr, "updated_at": "2026-01-01T00:00:00Z",
            "branch": None, **extra}


class Upstream:
    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.repos = ["o/r"]
        self.items = [item(1, "Bug", labels=["Bug"], assignees=["rvey"]), item(2, "Add feature", is_pr=True)]
        self.mode = "ok"
        self.endless = False  # next_page always set

    def __call__(self, request):
        self.calls.append(request)
        if self.mode == "down":
            raise httpx.ConnectError("boom", request=request)
        if self.mode == "429":
            return httpx.Response(429, json={"detail": "slow"}, headers={"Retry-After": "9"})
        path = request.url.path
        if path == "/link/v1/health":
            return httpx.Response(200, json=HEALTH)
        if path == "/link/v1/repos":
            return httpx.Response(200, json={"owner": "o", "installation_id": 7, "repos": [
                {"full_name": r, "private": False, "default_branch": "main"} for r in self.repos]})
        if path.endswith("/items"):
            q = request.url.params
            rows = [i for i in self.items if q["kind"] == "all" or (q["kind"] == "pr") == i["is_pr"]]
            rows = [i for i in rows if q["state"] == "all" or i["state"] == q["state"]]
            page = int(q["page"])
            return httpx.Response(200, json={"items": rows if page == 1 or self.endless else [],
                                             "next_page": page + 1 if self.endless else None})
        return httpx.Response(404, json={"detail": "not_found"})

    def items_calls(self):
        return [c for c in self.calls if c.url.path.endswith("/items")]


@pytest.fixture
def upstream(monkeypatch):
    fake = Upstream()
    monkeypatch.setattr(ab, "_transport_override", httpx.MockTransport(fake))
    ab._cache.clear()
    yield fake
    ab._cache.clear()


@pytest.fixture
def env(tmp_path, monkeypatch, upstream):
    engine = create_engine(f"sqlite:///{tmp_path / 'gi.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SessionLocal", factory)
    client = _signed_in_client(engine)
    with client:
        yield client, factory
    main.app.dependency_overrides.clear()
    engine.dispose()


def account(client, email, link=True):
    key = _register_account(client, email)
    ws = workspaces_of(client, key)[0]
    if link:
        r = client.put(f"/api/workspaces/{ws['id']}/affinebot", headers=H(key),
                       json={"base_url": "https://bot.example.com", "client_id": CID, "secret": SECRET})
        assert r.status_code == 200 and r.json()["status"] == "active", r.text
    return key, ws["id"], ws["projects"][0]["id"]


def test_repos_annotates_linked_and_guards_access(env, upstream, monkeypatch) -> None:
    client, _ = env
    alpha, wid, pid = account(client, "alpha@example.com")
    beta, *_ = account(client, "beta@example.com")
    upstream.repos = ["o/r", "o/other"]
    ab._cache.clear()
    url = f"/api/workspaces/{wid}/github/repos"
    rows = client.get(url, headers=H(alpha)).json()
    assert rows == [
        {"full_name": "o/r", "private": False, "default_branch": "main", "linked": False, "project_id": None},
        {"full_name": "o/other", "private": False, "default_branch": "main", "linked": False, "project_id": None},
    ]
    assert client.post("/api/github/links", json={"project_id": pid, "repo": "O/R"}, headers=H(alpha)).status_code == 201
    rows = {r["full_name"]: r for r in client.get(url, headers=H(alpha)).json()}
    assert rows["o/r"]["linked"] is True and rows["o/r"]["project_id"] == pid
    assert rows["o/other"]["linked"] is False
    assert SECRET not in client.get(url, headers=H(alpha)).text
    assert client.get(url, headers=H(beta)).status_code == 404  # non-member
    monkeypatch.setattr(main.settings, "updater_token", "shared-secret")
    assert client.get(url, headers=H("shared-secret")).status_code == 403


def test_repos_without_link_is_409(env) -> None:
    client, _ = env
    key, wid, _ = account(client, "alpha@example.com", link=False)
    r = client.get(f"/api/workspaces/{wid}/github/repos", headers=H(key))
    assert r.status_code == 409 and r.json()["detail"] == "affinebot_not_linked"


def test_items_task_id_annotation_cache_and_error_map(env, upstream) -> None:
    client, _ = env
    alpha, wid, pid = account(client, "alpha@example.com")
    clock = [1000.0]
    ab._cache.clock = lambda: clock[0]
    try:
        url = f"/api/workspaces/{wid}/github/items"
        first = client.get(url, params={"repo": "o/r"}, headers=H(alpha))
        assert first.status_code == 200, first.text
        data = first.json()
        assert data["next_page"] is None and [i["task_id"] for i in data["items"]] == [None, None]
        assert {"number", "title", "body", "state", "merged", "draft", "url", "author", "assignees", "labels",
                "comments", "is_pr", "updated_at", "branch", "task_id"} == set(data["items"][0])
        sync = client.post("/api/github/sync", json={"project_id": pid, "repo": "o/r"}, headers=H(alpha))
        assert sync.status_code == 200
        n = len(upstream.items_calls())
        again = client.get(url, params={"repo": "o/r"}, headers=H(alpha)).json()
        assert len(upstream.items_calls()) == n  # cache hit within TTL
        assert all(i["task_id"] for i in again["items"])  # annotated from the DB even on a cached payload
        tasks = {t["external_id"]: t["id"] for t in client.get("/api/tasks", headers=H(alpha)).json()}
        assert {i["number"]: i["task_id"] for i in again["items"]} == {1: tasks["github:o/r#1"], 2: tasks["github:o/r#2"]}
        clock[0] += 61
        client.get(url, params={"repo": "o/r"}, headers=H(alpha))
        assert len(upstream.items_calls()) == n + 1  # refetched after TTL
        pr_only = client.get(url, params={"repo": "o/r", "kind": "pr"}, headers=H(alpha)).json()
        assert [i["number"] for i in pr_only["items"]] == [2]
        assert client.get(url, params={"repo": "o/r", "kind": "bogus"}, headers=H(alpha)).status_code == 422
        assert client.get(url, params={"repo": "not a repo"}, headers=H(alpha)).status_code == 422
        # Error map
        clock[0] += 1000
        upstream.mode = "429"
        r = client.get(url, params={"repo": "o/r", "state": "closed"}, headers=H(alpha))
        assert r.status_code == 503 and r.headers["retry-after"] == "9"
        upstream.mode = "down"
        r = client.get(url, params={"repo": "o/r", "state": "all"}, headers=H(alpha))
        assert r.status_code == 502 and r.json()["detail"] == "affinebot_unreachable"
    finally:
        ab._cache.clock = __import__("time").monotonic


def test_sync_is_idempotent_maps_state_and_ignores_token(env, upstream) -> None:
    client, _ = env
    alpha, wid, pid = account(client, "alpha@example.com")
    body = {"project_id": pid, "repo": "https://github.com/o/r", "token": "ghp_shouldbeignored"}
    first = client.post("/api/github/sync", json=body, headers=H(alpha))
    assert first.status_code == 200, first.text
    assert first.json() == {"repo": "o/r", "created": 2, "updated": 0, "total": 2, "truncated": False}
    upstream.items[0].update(state="closed", title="Bug (fixed)")
    ab._cache.clear()
    second = client.post("/api/github/sync", json={**body, "state": "all"}, headers=H(alpha)).json()
    assert second["created"] == 0 and second["updated"] == 2
    tasks = {t["external_id"]: t for t in client.get("/api/tasks", params={"project_id": pid}, headers=H(alpha)).json()}
    assert len(tasks) == 2
    assert tasks["github:o/r#1"]["status"] == "done" and tasks["github:o/r#1"]["title"] == "Bug (fixed)"
    assert tasks["github:o/r#1"]["assignee"] == "rvey" and "bug" in tasks["github:o/r#1"]["tags"]
    assert tasks["github:o/r#2"]["status"] == "review"
    assert all("ghp_" not in (c.headers.get("authorization", "") + str(c.url)) for c in upstream.calls)
    assert client.post("/api/github/sync", json={**body, "repo": "not a repo"}, headers=H(alpha)).status_code == 422
    assert client.post("/api/github/sync", json={"repo": "o/r"}, headers=H(alpha)).status_code == 422  # project_id required
    only_issues = client.post("/api/github/sync", json={**body, "state": "all", "include_prs": False}, headers=H(alpha)).json()
    assert only_issues["total"] == 1
    for call in upstream.items_calls()[-1:]:
        assert call.url.params["kind"] == "issue"
    assert client.post("/api/github/sync", json={**body, "include_prs": False, "include_issues": False}, headers=H(alpha)).json()["total"] == 0
    assert SECRET not in first.text


def test_sync_truncates_at_page_cap(env, upstream) -> None:
    client, _ = env
    alpha, wid, pid = account(client, "alpha@example.com")
    upstream.endless = True
    r = client.post("/api/github/sync", json={"project_id": pid, "repo": "o/r"}, headers=H(alpha))
    assert r.status_code == 200 and r.json()["truncated"] is True
    assert len(upstream.items_calls()) == 10
    assert r.json()["total"] == 20  # same two rows returned on each of the 10 pages, upserted idempotently
    assert r.json()["created"] == 2 and r.json()["updated"] == 18


def test_sync_without_link_and_foreign_project(env) -> None:
    client, _ = env
    alpha, wid, pid = account(client, "alpha@example.com", link=False)
    beta, *_ = account(client, "beta@example.com")
    r = client.post("/api/github/sync", json={"project_id": pid, "repo": "o/r"}, headers=H(alpha))
    assert r.status_code == 409 and r.json()["detail"] == "affinebot_not_linked"
    assert client.post("/api/github/sync", json={"project_id": pid, "repo": "o/r"}, headers=H(beta)).status_code == 404
    assert client.post("/api/github/links", json={"project_id": pid, "repo": "o/r"}, headers=H(beta)).status_code == 404
    assert client.get("/api/github/links", params={"project_id": pid}, headers=H(beta)).status_code == 404


def test_links_verify_repo_and_return_initial_sync(env, upstream) -> None:
    client, factory = env
    alpha, wid, pid = account(client, "alpha@example.com")
    beta, _, pb = account(client, "beta@example.com")
    missing = client.post("/api/github/links", json={"project_id": pid, "repo": "o/secret"}, headers=H(alpha))
    assert missing.status_code == 404 and "not accessible" in missing.json()["detail"]
    with factory() as db:
        assert db.scalars(select(GitHubRepoLink)).all() == []
    ok = client.post("/api/github/links", json={"project_id": pid, "repo": "o/r", "token": "ignored"}, headers=H(alpha))
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["project_id"] == pid and body["repo"] == "o/r"
    assert body["sync"] == {"repo": "o/r", "created": 2, "updated": 0, "total": 2, "truncated": False}
    again = client.post("/api/github/links", json={"project_id": pid, "repo": "o/r"}, headers=H(alpha))
    assert again.json()["id"] == body["id"]
    assert [l["id"] for l in client.get("/api/github/links", headers=H(alpha)).json()] == [body["id"]]
    # Account B (different workspace, no link of its own to Affinebot) cannot see or touch A's data.
    assert client.get("/api/github/links", headers=H(beta)).json() == []
    assert client.get("/api/tasks", headers=H(beta)).json() == []
    assert client.delete(f"/api/github/links/{body['id']}", headers=H(beta)).status_code == 404
    assert SECRET not in ok.text


def test_webhook_live_sync_through_link(env, monkeypatch) -> None:
    client, _ = env
    monkeypatch.setattr(main.settings, "github_webhook_secret", "whsec")
    alpha, wid, pid = account(client, "alpha@example.com")

    def post(event, payload, secret="whsec"):
        raw = json.dumps(payload).encode()
        sig = "sha256=" + hmac_mod.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return client.post("/api/github/webhook", content=raw, headers={
            "x-github-event": event, "x-hub-signature-256": sig, "content-type": "application/json"})

    issue = {"number": 7, "title": "Crash", "body": "", "state": "open", "html_url": "https://github.com/o/r/issues/7", "labels": []}
    base = {"action": "opened", "repository": {"full_name": "O/R"}, "issue": issue}
    assert post("issues", base).json()["linked"] == 0
    link = client.post("/api/github/links", json={"project_id": pid, "repo": "o/r"}, headers=H(alpha)).json()
    assert post("issues", base).json()["linked"] == 1
    assert "github:o/r#7" in {t["external_id"] for t in client.get("/api/tasks", headers=H(alpha)).json()}
    issue["state"] = "closed"
    post("issues", {**base, "action": "closed"})
    tasks = {t["external_id"]: t for t in client.get("/api/tasks", headers=H(alpha)).json()}
    assert tasks["github:o/r#7"]["status"] == "done"
    assert post("issues", base, secret="wrong").status_code == 401
    assert post("ping", {"zen": "x"}).json()["pong"] is True
    assert client.get("/api/github/links", headers=H(alpha)).json()[0]["last_event_at"] is not None
    assert client.delete(f"/api/github/links/{link['id']}", headers=H(alpha)).status_code == 200
