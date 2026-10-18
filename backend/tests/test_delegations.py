"""Delegating tasks to Claude Code via Affinebot: routes, signed callback, webhook hint, sync numbers filter."""
import hashlib
import hmac as hmac_mod
import inspect
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import affinebot_client as ab
from app import delegation_routes, main
from app.config import get_settings
from app.db import Base, Delegation, Task, now_utc
from test_api import _register_account, _signed_in_client
from test_workspaces import H, workspaces_of

SECRET = "abl_supersecretvalue123"
CID = "33333333-3333-3333-3333-333333333333"
CB_SECRET = "callback-secret"
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
    monkeypatch.setattr(get_settings(), "affinebot_callback_secret", CB_SECRET)
    monkeypatch.setattr(get_settings(), "updater_public_url", "https://updater.example.com/")
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


def sign(body: bytes, secret=CB_SECRET) -> dict:
    return {"X-Affinebot-Signature": "sha256=" + hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


def callback(client, did, payload, secret=CB_SECRET):
    body = json.dumps(payload).encode()
    return client.post(f"/api/delegations/{did}/status", content=body, headers=sign(body, secret))


def delegate(client, key, task_id, **body):
    return client.post(f"/api/tasks/{task_id}/delegate", json=body, headers=H(key))


def test_delegate_creates_queued_row_and_calls_affinebot(env, upstream) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    tid = make_task(factory, pid)
    r = delegate(client, key, tid, instruction="Be careful", base_branch="dev")
    assert r.status_code == 201, r.text
    data = r.json()
    assert set(data) == {"id", "task_id", "project_id", "repo", "issue_number", "status", "branch", "pr_url",
                         "pr_number", "error", "summary", "created_at", "updated_at", "finished_at"}
    assert data["status"] == "queued" and data["repo"] == "o/r" and data["issue_number"] == 5 and data["task_id"] == tid
    post = upstream.delegation_posts()[0]
    assert post.headers["authorization"] == f"Bearer {SECRET}" and post.headers["x-link-client"] == CID
    sent = json.loads(post.content)
    assert sent["delegation_id"] == data["id"] and sent["repo"] == "o/r" and sent["issue_number"] == 5
    assert sent["base_branch"] == "dev" and sent["callback_url"] == f"https://updater.example.com/api/delegations/{data['id']}/status"
    assert "Fix login" in sent["instruction"] and "Be careful" in sent["instruction"]
    with factory() as db:
        assert db.get(Delegation, data["id"]).remote_id == "rem-1"
    # body is optional
    assert client.post(f"/api/tasks/{tid}/delegate", headers=H(key)).status_code == 201


def test_second_delegate_returns_active_row_then_new_after_terminal(env, upstream) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    tid = make_task(factory, pid)
    first = delegate(client, key, tid).json()
    second = delegate(client, key, tid).json()
    assert second["id"] == first["id"] and len(upstream.delegation_posts()) == 1
    assert callback(client, first["id"], {"status": "failed", "error": "boom"}).status_code == 200
    third = delegate(client, key, tid).json()
    assert third["id"] != first["id"] and third["status"] == "queued"
    listed = client.get(f"/api/tasks/{tid}/delegations", headers=H(key)).json()
    assert [d["id"] for d in listed] == [third["id"], first["id"]]


@pytest.mark.parametrize("mode", ["down", "500"])
def test_affinebot_failure_stores_failed_and_returns_201(env, upstream, mode) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    tid = make_task(factory, pid)
    upstream.mode = mode
    r = delegate(client, key, tid)
    assert r.status_code == 201
    assert r.json()["status"] == "failed" and r.json()["error"] and r.json()["finished_at"]
    upstream.mode = "ok"
    assert delegate(client, key, tid).json()["status"] == "queued"  # failed is not active


def test_delegate_guards(env, upstream, monkeypatch) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
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
    monkeypatch.setattr(get_settings(), "updater_public_url", "")
    r = delegate(client, key, tid)
    assert r.status_code == 503 and r.json()["detail"] == "updater_public_url_not_configured"
    monkeypatch.setattr(main.settings, "updater_token", "shared")
    assert delegate(client, "shared", tid).status_code == 403


def test_no_link_is_409(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com", link=False)
    r = delegate(client, key, make_task(factory, pid))
    assert r.status_code == 409 and r.json()["detail"] == "affinebot_not_linked"


def test_other_account_gets_404_everywhere(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    other, _ = account(client, "b@example.com")
    tid = make_task(factory, pid)
    did = delegate(client, key, tid).json()["id"]
    assert client.get(f"/api/tasks/{tid}/delegations", headers=H(other)).status_code == 404
    assert client.get(f"/api/delegations/{did}", headers=H(other)).status_code == 404
    assert client.post(f"/api/delegations/{did}/cancel", headers=H(other)).status_code == 404
    assert client.get(f"/api/delegations/{did}", headers=H(key)).status_code == 200


def test_callback_signature_and_flow(env) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    tid = make_task(factory, pid)
    did = delegate(client, key, tid).json()["id"]
    url = f"/api/delegations/{did}/status"
    body = json.dumps({"status": "running"}).encode()
    assert client.post(url, content=body).status_code == 401  # missing
    assert client.post(url, content=body, headers={"X-Affinebot-Signature": "sha256=" + "0" * 64}).status_code == 401
    assert client.post(url, content=body, headers=sign(body, "wrong")).status_code == 401
    # no Authorization header needed
    r = callback(client, did, {"status": "running", "branch": "claude/abc"})
    assert r.status_code == 200 and r.json()["status"] == "running" and r.json()["branch"] == "claude/abc"
    pr = "https://github.com/o/r/pull/9"
    r = callback(client, did, {"status": "pr_opened", "pr_url": pr, "pr_number": 9, "summary": "done"})
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "pr_opened" and out["pr_url"] == pr and out["pr_number"] == 9 and out["finished_at"]
    with factory() as db:
        task = db.get(Task, tid)
        assert task.status == "review" and task.external_url == pr and "claude-code" in task.tags
    # late running and duplicate pr_opened are ignored with 200
    late = callback(client, did, {"status": "running"})
    assert late.status_code == 200 and late.json()["status"] == "pr_opened"
    assert callback(client, did, {"status": "failed", "error": "x"}).json()["status"] == "pr_opened"
    assert callback(client, "nope", {"status": "running"}).status_code == 404


def test_callback_validation(env, monkeypatch) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    for bad in ["https://evil.com/o/r/pull/1", "https://github.com/o/other/pull/1", "https://github.com/o/r/issues/1",
                "http://github.com/o/r/pull/1", "https://github.com/o/r/pull/x"]:
        assert callback(client, did, {"status": "pr_opened", "pr_url": bad}).status_code == 422, bad
    assert callback(client, did, {"status": "pr_opened"}).status_code == 422
    assert callback(client, did, {"status": "cancelled"}).status_code == 422
    assert callback(client, did, {"status": "failed", "error": "e" * 5000}).status_code == 200
    with factory() as db:
        assert len(db.get(Delegation, did).error) == 2000
    monkeypatch.setattr(get_settings(), "affinebot_callback_secret", "")
    assert callback(client, did, {"status": "running"}).status_code == 503  # fails closed


def test_signature_uses_constant_time_compare() -> None:
    from app import github_sync
    assert "compare_digest" in inspect.getsource(github_sync.verify_signature)
    assert "verify_signature" in inspect.getsource(delegation_routes.delegation_callback)


def test_webhook_branch_fills_lost_callback(env, monkeypatch) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    tid = make_task(factory, pid)
    did = delegate(client, key, tid).json()["id"]
    monkeypatch.setattr(main.settings, "github_webhook_secret", "whsec")
    payload = {"action": "opened", "repository": {"full_name": "o/r"}, "pull_request": {
        "number": 12, "title": "t", "body": "", "state": "open", "html_url": "https://github.com/o/r/pull/12",
        "head": {"ref": "affinebot/claude-rem-1"}}}
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac_mod.new(b"whsec", body, hashlib.sha256).hexdigest()
    r = client.post("/api/github/webhook", content=body, headers={"x-hub-signature-256": sig, "x-github-event": "pull_request"})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/delegations/{did}", headers=H(key)).json()
    assert got["status"] == "pr_opened" and got["pr_url"] == "https://github.com/o/r/pull/12" and got["pr_number"] == 12
    with factory() as db:
        assert db.get(Task, tid).status == "review"


def test_webhook_ignores_unrelated_branch(env, monkeypatch) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    monkeypatch.setattr(main.settings, "github_webhook_secret", "whsec")
    payload = {"action": "opened", "repository": {"full_name": "o/r"}, "pull_request": {
        "number": 12, "title": "t", "body": "", "state": "open", "html_url": "https://github.com/o/r/pull/12",
        "head": {"ref": "affinebot/claude-zzzzzzzz"}}}
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac_mod.new(b"whsec", body, hashlib.sha256).hexdigest()
    client.post("/api/github/webhook", content=body, headers={"x-hub-signature-256": sig, "x-github-event": "pull_request"})
    assert client.get(f"/api/delegations/{did}", headers=H(key)).json()["status"] == "queued"


def test_lazy_poll_refresh_after_60s(env, upstream) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    gets = lambda: [c for c in upstream.calls if c.method == "GET" and c.url.path == "/link/v1/delegations/rem-1"]  # noqa: E731
    assert client.get(f"/api/delegations/{did}", headers=H(key)).json()["status"] == "queued"
    assert gets() == []  # fresh: no poll
    with factory() as db:
        db.get(Delegation, did).updated_at = now_utc() - timedelta(seconds=120)
        db.commit()
    assert client.get(f"/api/delegations/{did}", headers=H(key)).json()["status"] == "running"
    assert len(gets()) == 1
    client.get(f"/api/delegations/{did}", headers=H(key))
    assert len(gets()) == 1  # throttled after a poll
    # Affinebot errors are swallowed
    with factory() as db:
        db.get(Delegation, did).updated_at = now_utc() - timedelta(seconds=120)
        db.commit()
    upstream.mode = "down"
    assert client.get(f"/api/delegations/{did}", headers=H(key)).status_code == 200


def test_lazy_poll_rejects_bad_pr_url_and_applies_good(env, upstream) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    tid = make_task(factory, pid)
    did = delegate(client, key, tid).json()["id"]

    def age():
        with factory() as db:
            db.get(Delegation, did).updated_at = now_utc() - timedelta(seconds=120)
            db.commit()

    upstream.remote = {**upstream.remote, "status": "pr_opened", "pr_url": "https://evil.com/x", "pr_number": 1}
    age()
    assert client.get(f"/api/delegations/{did}", headers=H(key)).json()["status"] == "queued"
    upstream.remote["pr_url"] = "https://github.com/o/r/pull/3"
    age()
    assert client.get(f"/api/delegations/{did}", headers=H(key)).json()["status"] == "pr_opened"
    with factory() as db:
        assert db.get(Task, tid).status == "review"


def test_cancel(env, upstream) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    r = client.post(f"/api/delegations/{did}/cancel", headers=H(key))
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["finished_at"]
    assert any(c.url.path == "/link/v1/delegations/rem-1/cancel" for c in upstream.calls)
    # cancelled is terminal: callbacks cannot revive it; cancelling again is a no-op
    assert callback(client, did, {"status": "running"}).json()["status"] == "cancelled"
    assert client.post(f"/api/delegations/{did}/cancel", headers=H(key)).json()["status"] == "cancelled"


def test_cancel_when_affinebot_down(env, upstream) -> None:
    client, factory = env
    key, pid = account(client, "a@example.com")
    did = delegate(client, key, make_task(factory, pid)).json()["id"]
    upstream.mode = "down"
    assert client.post(f"/api/delegations/{did}/cancel", headers=H(key)).json()["status"] == "cancelled"


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
