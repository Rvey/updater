"""Delegating tasks to the user's own agent: queue, claim, report, cancel, webhook hint, MCP tools; plus sync numbers filter."""
import hashlib
import hmac as hmac_mod
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import affinebot_client as ab
from app import main, mcp_server
from app.config import get_settings
from app.db import Base, Delegation, Task, now_utc
from test_api import _register_account, _signed_in_client
from test_workspaces import H, workspaces_of

SECRET = "abl_supersecretvalue123"
CID = "33333333-3333-3333-3333-333333333333"
HEALTH = {"ok": True, "app": "affinebot", "version": "1", "github_app": True, "redis": True, "db": True,
          "client": {"client_id": CID, "owner": "o", "installation_id": 7}}


class Upstream:
    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.mode = "ok"
        self.remote = {"status": "running", "branch": "claude/x", "pr_url": None, "pr_number": None, "error": None, "summary": None}
        self.items = [{"number": n, "title": f"I{n}", "body": "", "state": "open", "merged": False, "draft": False,
                       "url": f"https://github.com/o/r/issues/{n}", "author": "x", "assignees": [], "labels": [],
                       "comments": 0, "is_pr": False, "updated_at": "", "branch": None} for n in (1, 2, 3)]
        self.endless = False

    def __call__(self, request):
        self.calls.append(request)
        if self.mode == "down":
            raise httpx.ConnectError("boom", request=request)
        if self.mode == "500":
            return httpx.Response(500, text="x")
        path = request.url.path
        if path == "/link/v1/health":
            return httpx.Response(200, json=HEALTH)
        if path == "/link/v1/repos":
            return httpx.Response(200, json={"owner": "o", "installation_id": 7, "repos": [{"full_name": "o/r", "private": False, "default_branch": "main"}]})
        if path.endswith("/items"):
            page = int(request.url.params["page"])
            return httpx.Response(200, json={"items": self.items if page == 1 or self.endless else [], "next_page": page + 1 if self.endless else None})
        if path == "/link/v1/delegations":
            return httpx.Response(202, json={"remote_id": "rem-1", "status": "queued"})
        if path.endswith("/cancel"):
            return httpx.Response(200, json={**self.remote, "status": "cancelled"})
        if path.startswith("/link/v1/delegations/"):
            return httpx.Response(200, json=self.remote)
        return httpx.Response(404, json={"detail": "not_found"})

    def delegation_posts(self):
        return [c for c in self.calls if c.method == "POST" and c.url.path == "/link/v1/delegations"]


@pytest.fixture
def upstream(monkeypatch):
    fake = Upstream()
    monkeypatch.setattr(ab, "_transport_override", httpx.MockTransport(fake))
    ab._cache.clear()
    yield fake
    ab._cache.clear()


@pytest.fixture
def env(tmp_path, monkeypatch, upstream):
    engine = create_engine(f"sqlite:///{tmp_path / 'd.sqlite3'}", connect_args={"check_same_thread": False})
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
        assert r.status_code == 200, r.text
    return key, ws["projects"][0]["id"]


def make_task(factory, project_id, **kw):
    with factory() as db:
        task = Task(project_id=project_id, title="Fix login", description="Users cannot log in", status="backlog",
                    external_id="github:o/r#5", tags=["github"], **kw)
        db.add(task)
        db.commit()
        return task.id


def delegate(client, key, task_id, **body):
    return client.post(f"/api/tasks/{task_id}/delegate", json=body, headers=H(key))


def claim(client, key, did, agent="test-agent"):
    return client.post(f"/api/delegations/{did}/claim", json={"agent": agent}, headers=H(key))


def report(client, key, did, **body):
    return client.post(f"/api/delegations/{did}/report", json=body, headers=H(key))


PR = "https://github.com/o/r/pull/9"
KEYS = {"id", "task_id", "project_id", "repo", "issue_number", "status", "branch", "pr_url", "pr_number", "error", "summary",
        "created_at", "updated_at", "finished_at", "task_title", "task_description", "issue_url", "suggested_branch",
        "instruction", "base_branch", "claimed_by", "claimed_at"}


def test_delegate_creates_queued_row_without_affinebot(env, upstream, monkeypatch) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)  # no Affinebot link needed
    tid = make_task(factory, pid)
    r = delegate(client, key, tid, instruction="Be careful", base_branch="dev")
    assert r.status_code == 201, r.text
    data = r.json()
    assert set(data) == KEYS
    assert data["status"] == "queued" and data["repo"] == "o/r" and data["issue_number"] == 5 and data["task_id"] == tid
    assert data["task_title"] == "Fix login" and data["task_description"] == "Users cannot log in"
    assert data["suggested_branch"] == f"updater/delegation-{data['id'][:8]}" and data["base_branch"] == "dev"
    assert data["issue_url"] == "https://github.com/o/r/issues/5" and data["claimed_by"] is None and data["claimed_at"] is None
    assert "Fix login" in data["instruction"] and "Be careful" in data["instruction"]
    assert upstream.calls == []  # no Affinebot call
    assert client.post(f"/api/tasks/{tid}/delegate", headers=H(key)).json()["id"] == data["id"]  # body optional, one active per task


def test_issue_url_uses_task_external_url(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    tid = make_task(factory, pid, external_url="https://github.com/o/r/issues/5")
    assert delegate(client, key, tid).json()["issue_url"] == "https://github.com/o/r/issues/5"


def test_new_delegation_after_terminal_and_task_listing(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    tid = make_task(factory, pid)
    first = delegate(client, key, tid).json()
    assert report(client, key, first["id"], status="failed", error="boom").status_code == 200
    third = delegate(client, key, tid).json()
    assert third["id"] != first["id"] and third["status"] == "queued"
    listed = client.get(f"/api/tasks/{tid}/delegations", headers=H(key)).json()
    assert [d["id"] for d in listed] == [third["id"], first["id"]]


def test_delegate_guards(env, monkeypatch) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    other, _ = account(client, "b@example.com", link=False)
    with factory() as db:
        plain = Task(project_id=pid, title="No repo", status="backlog")
        viaurl = Task(project_id=pid, title="Via url", status="backlog", repo_url="https://github.com/Acme/Web")
        db.add_all([plain, viaurl])
        db.commit()
        plain_id, url_id = plain.id, viaurl.id
    assert delegate(client, key, plain_id).status_code == 422
    r = delegate(client, key, url_id)
    assert r.status_code == 201 and r.json()["repo"] == "acme/web" and r.json()["issue_number"] is None
    tid = make_task(factory, pid)
    assert delegate(client, other, tid).status_code == 404
    monkeypatch.setattr(main.settings, "updater_token", "shared")
    assert delegate(client, "shared", tid).status_code == 403


def test_list_own_delegations_only_with_filters(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    other, opid = account(client, "b@example.com", link=False)
    older = delegate(client, key, make_task(factory, pid)).json()
    with factory() as db:
        db.get(Delegation, older["id"]).created_at = now_utc() - timedelta(hours=1)
        web = Task(project_id=pid, title="Web", status="backlog", repo_url="https://github.com/Acme/Web")
        db.add(web)
        db.commit()
        web_id = web.id
    newer = delegate(client, key, web_id).json()
    theirs = delegate(client, other, make_task(factory, opid)).json()
    got = client.get("/api/delegations", headers=H(key)).json()
    assert [d["id"] for d in got] == [newer["id"], older["id"]]  # newest first, own only
    assert [d["id"] for d in client.get("/api/delegations", headers=H(other)).json()] == [theirs["id"]]
    for repo in ("acme/web", "Acme/Web", "https://github.com/Acme/Web.git", "git@github.com:acme/web.git"):
        got = client.get("/api/delegations", params={"repo": repo}, headers=H(key)).json()
        assert [d["id"] for d in got] == [newer["id"]], repo
    claim(client, key, older["id"])
    assert [d["id"] for d in client.get("/api/delegations", headers=H(key)).json()] == [newer["id"]]  # default status=queued
    both = client.get("/api/delegations", params={"status": "queued,running"}, headers=H(key)).json()
    assert {d["id"] for d in both} == {newer["id"], older["id"]}
    assert client.get("/api/delegations", params={"status": "running"}, headers=H(key)).json()[0]["id"] == older["id"]


def test_claim_by_creator_other_user_and_stale(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    other, _ = account(client, "b@example.com", link=False)
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    assert claim(client, other, did).status_code == 404
    assert client.get(f"/api/delegations/{did}", headers=H(other)).status_code == 404
    assert claim(client, key, "nope").status_code == 404
    r = claim(client, key, did, agent="claude-code")
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "running" and out["claimed_by"] == "claude-code" and out["claimed_at"]
    assert claim(client, key, did).status_code == 409  # fresh claim
    with factory() as db:
        db.get(Delegation, did).claimed_at = now_utc() - timedelta(minutes=29)
        db.commit()
    assert claim(client, key, did).status_code == 409
    with factory() as db:
        db.get(Delegation, did).claimed_at = now_utc() - timedelta(minutes=31)
        db.commit()
    r = claim(client, key, did, agent="codex")
    assert r.status_code == 200 and r.json()["claimed_by"] == "codex" and r.json()["status"] == "running"
    # a finished delegation cannot be claimed again
    assert report(client, key, did, status="failed", error="x").status_code == 200
    assert claim(client, key, did).status_code == 409


def test_env_token_cannot_claim_or_report(env, monkeypatch) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    monkeypatch.setattr(main.settings, "updater_token", "shared")
    assert claim(client, "shared", did).status_code == 403
    assert report(client, "shared", did, status="running").status_code == 403
    assert client.get("/api/delegations", headers=H("shared")).status_code == 403


def test_report_flow_forward_only_and_task_to_review(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    other, _ = account(client, "b@example.com", link=False)
    tid = make_task(factory, pid)
    did = delegate(client, key, tid).json()["id"]
    assert report(client, other, did, status="running").status_code == 404  # creator only
    assert claim(client, key, did).status_code == 200
    r = report(client, key, did, status="running", branch="updater/delegation-x")
    assert r.status_code == 200 and r.json()["status"] == "running"
    r = report(client, key, did, status="pr_opened", branch=f"updater/delegation-{did[:8]}", pr_url=PR, pr_number=9,
               summary="done", repo_url="git@github.com:O/R.git")
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "pr_opened" and out["pr_url"] == PR and out["pr_number"] == 9 and out["finished_at"] and out["summary"] == "done"
    with factory() as db:
        task = db.get(Task, tid)
        assert task.status == "review" and task.external_url == PR and "claude-code" in task.tags
    # late running, duplicate pr_opened and failed are ignored with 200
    assert report(client, key, did, status="running").json()["status"] == "pr_opened"
    assert report(client, key, did, status="failed", error="x").json()["status"] == "pr_opened"
    dup = report(client, key, did, status="pr_opened", pr_url="https://github.com/o/r/pull/10", pr_number=10)
    assert dup.status_code == 200 and dup.json()["pr_url"] == PR
    assert report(client, key, "nope", status="running").status_code == 404


def test_report_keeps_existing_external_url(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    tid = make_task(factory, pid, external_url="https://github.com/o/r/issues/5")
    did = delegate(client, key, tid).json()["id"]
    assert report(client, key, did, status="pr_opened", pr_url=PR, pr_number=9).status_code == 200
    with factory() as db:
        assert db.get(Task, tid).external_url == "https://github.com/o/r/issues/5"


def test_report_validation(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    for bad in ["https://evil.com/o/r/pull/1", "https://github.com/o/other/pull/1", "https://github.com/o/r/issues/1",
                "http://github.com/o/r/pull/1", "https://github.com/o/r/pull/x"]:
        assert report(client, key, did, status="pr_opened", pr_url=bad).status_code == 422, bad
    assert report(client, key, did, status="pr_opened").status_code == 422
    assert report(client, key, did, status="cancelled").status_code == 422
    assert report(client, key, did, status="bogus").status_code == 422
    r = report(client, key, did, status="failed", error="e" * 3900)
    assert r.status_code == 200
    with factory() as db:
        assert len(db.get(Delegation, did).error) == 2000


def test_report_wrong_checkout_is_409(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    r = report(client, key, did, status="pr_opened", pr_url=PR, pr_number=9, repo_url="https://github.com/o/other.git")
    assert r.status_code == 409 and "wrong checkout" in r.json()["detail"].lower()
    assert client.get(f"/api/delegations/{did}", headers=H(key)).json()["status"] == "queued"
    ok = report(client, key, did, status="running", repo_url="https://github.com/O/R/")
    assert ok.status_code == 200 and ok.json()["status"] == "running"


def test_cancel_is_local_and_terminal(env, upstream) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")  # linked, yet cancel must not call Affinebot
    other, _ = account(client, "b@example.com", link=False)
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    assert client.post(f"/api/delegations/{did}/cancel", headers=H(other)).status_code == 404
    before = len(upstream.calls)
    r = client.post(f"/api/delegations/{did}/cancel", headers=H(key))
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["finished_at"]
    assert len(upstream.calls) == before
    # cancelled is terminal: claim and reports cannot revive it; cancelling again is a no-op
    assert claim(client, key, did).status_code == 409
    assert report(client, key, did, status="running").json()["status"] == "cancelled"
    assert report(client, key, did, status="pr_opened", pr_url=PR, pr_number=9).json()["status"] == "cancelled"
    assert client.post(f"/api/delegations/{did}/cancel", headers=H(key)).json()["status"] == "cancelled"


def test_old_callback_route_removed(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    assert client.post(f"/api/delegations/{did}/status", json={"status": "running"}, headers=H(key)).status_code in (404, 405)
    assert not hasattr(get_settings(), "affinebot_callback_secret") and not hasattr(get_settings(), "updater_public_url")


def _webhook(client, monkeypatch, ref, repo="o/r", number=12):
    monkeypatch.setattr(main.settings, "github_webhook_secret", "whsec")
    payload = {"action": "opened", "repository": {"full_name": repo}, "pull_request": {
        "number": number, "title": "t", "body": "", "state": "open", "html_url": f"https://github.com/{repo}/pull/{number}",
        "head": {"ref": ref}}}
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac_mod.new(b"whsec", body, hashlib.sha256).hexdigest()
    return client.post("/api/github/webhook", content=body, headers={"x-hub-signature-256": sig, "x-github-event": "pull_request"})


def test_webhook_branch_fills_lost_report(env, monkeypatch) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    tid = make_task(factory, pid)
    d = delegate(client, key, tid).json()
    claim(client, key, d["id"])
    r = _webhook(client, monkeypatch, d["suggested_branch"])
    assert r.status_code == 200, r.text
    got = client.get(f"/api/delegations/{d['id']}", headers=H(key)).json()
    assert got["status"] == "pr_opened" and got["pr_url"] == "https://github.com/o/r/pull/12" and got["pr_number"] == 12
    with factory() as db:
        assert db.get(Task, tid).status == "review"


def test_webhook_ignores_unrelated_branch(env, monkeypatch) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    for ref in ("updater/delegation-zzzzzzzz", "affinebot/claude-" + did[:8], "feature/x"):
        assert _webhook(client, monkeypatch, ref).status_code == 200
    assert client.get(f"/api/delegations/{did}", headers=H(key)).json()["status"] == "queued"
    assert _webhook(client, monkeypatch, f"updater/delegation-{did[:8]}", repo="o/elsewhere").status_code == 200
    assert client.get(f"/api/delegations/{did}", headers=H(key)).json()["status"] == "queued"


def test_mcp_delegation_tools(monkeypatch) -> None:
    import asyncio

    calls = []

    async def fake(method, path, payload=None, authorization=""):
        calls.append((method, path, payload))
        return [{"id": "d1"}] if method == "GET" else {"id": "d1", "status": "running"}

    monkeypatch.setattr(mcp_server, "api_request", fake)
    out = asyncio.run(mcp_server.list_delegations(repo="https://github.com/o/r"))
    assert out == {"count": 1, "delegations": [{"id": "d1"}]}
    assert calls[0] == ("GET", "/api/delegations?status=queued&repo=https%3A%2F%2Fgithub.com%2Fo%2Fr", None)
    asyncio.run(mcp_server.claim_delegation("d1", agent="claude"))
    assert calls[1] == ("POST", "/api/delegations/d1/claim", {"agent": "claude"})
    asyncio.run(mcp_server.report_delegation("d1", "pr_opened", branch="b", pr_url=PR, pr_number=9, summary="s", repo_url="u"))
    assert calls[2] == ("POST", "/api/delegations/d1/report", {
        "status": "pr_opened", "branch": "b", "pr_url": PR, "pr_number": 9, "summary": "s", "error": None, "repo_url": "u"})
    asyncio.run(mcp_server.report_delegation("d1", "failed", error="boom"))
    assert calls[3][2] == {"status": "failed", "branch": None, "pr_url": None, "pr_number": None, "summary": None, "error": "boom", "repo_url": None}


def test_sync_numbers_filter_and_early_stop(env, upstream) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    body = {"project_id": pid, "repo": "o/r", "numbers": [2]}
    r = client.post("/api/github/sync", json=body, headers=H(key))
    assert r.status_code == 200 and r.json()["total"] == 1 and r.json()["created"] == 1
    with factory() as db:
        assert [t.external_id for t in db.query(Task).all()] == ["github:o/r#2"]
    # endless pagination: stops once every requested number was found
    upstream.endless = True
    ab._cache.clear()
    before = len([c for c in upstream.calls if c.url.path.endswith("/items")])
    r = client.post("/api/github/sync", json={**body, "numbers": [1, 3]}, headers=H(key))
    assert r.json()["total"] == 2 and r.json()["truncated"] is False
    assert len([c for c in upstream.calls if c.url.path.endswith("/items")]) - before == 1
    # a number that never appears paginates to the cap and reports truncated
    r = client.post("/api/github/sync", json={**body, "numbers": [99]}, headers=H(key))
    assert r.json()["total"] == 0 and r.json()["truncated"] is True
    # without numbers: unchanged behavior (all items)
    upstream.endless = False
    ab._cache.clear()
    assert client.post("/api/github/sync", json={"project_id": pid, "repo": "o/r"}, headers=H(key)).json()["total"] == 3
