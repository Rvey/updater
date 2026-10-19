"""Affinebot link: client (MockTransport), secret box, TTL cache and the /affinebot routes."""
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import affinebot_client as ab
from app import main
from app.config import get_settings
from app.db import AffinebotLink, Base
from app.secrets_box import decrypt_secret, encrypt_secret
from test_api import _register_account, _signed_in_client
from test_workspaces import H, workspaces_of

SECRET = "abl_supersecretvalue123"
CID = "11111111-1111-1111-1111-111111111111"
BODY = {"base_url": "https://bot.example.com/", "client_id": CID, "secret": SECRET}

HEALTH = {"ok": True, "app": "affinebot", "version": "1", "github_app": True, "redis": True, "db": True,
          "client": {"client_id": CID, "owner": "acme", "installation_id": 42}}
REPOS = {"owner": "acme", "installation_id": 42, "repos": [{"full_name": "acme/web", "private": False, "default_branch": "main"}]}


class Upstream:
    """Scriptable fake Affinebot recording every request."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.mode = "ok"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.mode == "down":
            raise httpx.ConnectError("boom", request=request)
        if self.mode == "401":
            return httpx.Response(401, json={"detail": "unauthorized"})
        if self.mode == "500":
            return httpx.Response(500, text="oops")
        if self.mode == "429":
            return httpx.Response(429, json={"detail": "slow"}, headers={"Retry-After": "7"})
        path = request.url.path
        if path == "/link/v1/health":
            return httpx.Response(200, json=HEALTH)
        if path == "/link/v1/repos":
            return httpx.Response(200, json=REPOS)
        if path.endswith("/items"):
            return httpx.Response(200, json={"items": [], "next_page": None})
        if path == "/link/v1/delegations":
            return httpx.Response(202, json={"remote_id": "r1", "status": "queued"})
        if path.startswith("/link/v1/delegations/"):
            return httpx.Response(200, json={"status": "running", "branch": None, "pr_url": None, "pr_number": None, "error": None, "summary": None})
        return httpx.Response(404, json={"detail": "not_found"})


@pytest.fixture
def upstream(monkeypatch):
    fake = Upstream()
    monkeypatch.setattr(ab, "_transport_override", httpx.MockTransport(fake))
    ab._cache.clear()
    yield fake
    ab._cache.clear()


@pytest.fixture
def env(tmp_path, monkeypatch, upstream):
    engine = create_engine(f"sqlite:///{tmp_path / 'ab.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SessionLocal", factory)
    client = _signed_in_client(engine)
    with client:
        owner = _register_account(client, "owner@example.com")
        wid = workspaces_of(client, owner)[0]["id"]
        yield client, factory, owner, wid
    main.app.dependency_overrides.clear()
    engine.dispose()


def url(wid, tail=""):
    return f"/api/workspaces/{wid}/affinebot{tail}"


def test_put_stores_and_never_returns_secret(env, upstream) -> None:
    client, factory, owner, wid = env
    put = client.put(url(wid), json=BODY, headers=H(owner))
    assert put.status_code == 200, put.text
    data = put.json()
    assert set(data) == {"workspace_id", "base_url", "client_id", "status", "github_owner", "installation_id", "last_checked_at", "last_error"}
    assert data["status"] == "active" and data["github_owner"] == "acme" and data["installation_id"] == 42
    assert data["base_url"] == "https://bot.example.com" and data["last_error"] is None
    got = client.get(url(wid), headers=H(owner))
    assert got.status_code == 200 and SECRET not in got.text and SECRET not in put.text
    for call in upstream.calls:
        assert call.headers["authorization"] == f"Bearer {SECRET}" and call.headers["x-link-client"] == CID
    # 422 bodies do not echo the secret either
    bad = client.put(url(wid), json={**BODY, "base_url": "file:///etc/passwd"}, headers=H(owner))
    assert bad.status_code == 422 and SECRET not in bad.text
    bad = client.put(url(wid), json={"base_url": "https://x.io", "secret": SECRET}, headers=H(owner))
    assert bad.status_code == 422 and SECRET not in bad.text


def test_base_url_validation(env) -> None:
    client, _, owner, wid = env
    for bad in ["file:///x", "ftp://x.io", "https://user:pw@bot.example.com", "https://bot.example.com/#frag", "nonsense"]:
        assert client.put(url(wid), json={**BODY, "base_url": bad}, headers=H(owner)).status_code == 422, bad
    assert client.get(url(wid), headers=H(owner)).status_code == 404


def test_check_records_status_and_errors(env, upstream) -> None:
    client, _, owner, wid = env
    client.put(url(wid), json=BODY, headers=H(owner))
    upstream.mode = "down"
    checked = client.post(url(wid, "/check"), headers=H(owner))
    assert checked.status_code == 200
    assert checked.json()["status"] == "error" and checked.json()["last_error"] == "affinebot_unreachable"
    upstream.mode = "401"
    assert client.post(url(wid, "/check"), headers=H(owner)).json()["last_error"] == "affinebot_rejected"
    upstream.mode = "ok"
    again = client.post(url(wid, "/check"), headers=H(owner)).json()
    assert again["status"] == "active" and again["last_error"] is None and again["last_checked_at"]


def test_put_with_failing_upstream_still_stores_row(env, upstream) -> None:
    client, factory, owner, wid = env
    upstream.mode = "down"
    put = client.put(url(wid), json=BODY, headers=H(owner))
    assert put.status_code == 200 and put.json()["status"] == "error"
    assert put.json()["last_error"] == "affinebot_unreachable" and SECRET not in put.text
    upstream.mode = "401"
    assert client.put(url(wid), json=BODY, headers=H(owner)).json()["last_error"] == "affinebot_rejected"
    with factory() as db:
        assert db.query(AffinebotLink).count() == 1


def test_delete_and_permissions(env) -> None:
    client, _, owner, wid = env
    assert client.get(url(wid), headers=H(owner)).status_code == 404
    client.put(url(wid), json=BODY, headers=H(owner))
    stranger = _register_account(client, "stranger@example.com")
    for call in (lambda h: client.get(url(wid), headers=h), lambda h: client.post(url(wid, "/check"), headers=h),
                 lambda h: client.put(url(wid), json=BODY, headers=h), lambda h: client.delete(url(wid), headers=h)):
        assert call(H(stranger)).status_code == 404
    # member (not owner): may read and check, not PUT/DELETE
    invite = client.post(f"/api/workspaces/{wid}/invites", json={"email": "stranger@example.com"}, headers=H(owner)).json()
    accepted = client.post("/api/invites/accept", json={"token": invite["token"]}, headers=H(stranger))
    assert accepted.status_code == 200, accepted.text
    assert client.get(url(wid), headers=H(stranger)).status_code == 200
    assert client.post(url(wid, "/check"), headers=H(stranger)).status_code == 200
    assert client.put(url(wid), json=BODY, headers=H(stranger)).status_code == 403
    assert client.delete(url(wid), headers=H(stranger)).status_code == 403
    assert client.delete(url(wid), headers=H(owner)).status_code == 204
    assert client.get(url(wid), headers=H(owner)).status_code == 404
    assert client.delete(url(wid), headers=H(owner)).status_code == 404


def test_env_token_forbidden(env, monkeypatch) -> None:
    client, _, _, wid = env
    monkeypatch.setattr(get_settings(), "updater_token", "shared-secret")
    assert client.get(url(wid), headers=H("shared-secret")).status_code == 403
    assert client.put(url(wid), json=BODY, headers=H("shared-secret")).status_code == 403
    assert client.get(url(wid)).status_code == 401


def test_secret_encrypted_at_rest_when_key_set(env, monkeypatch) -> None:
    client, factory, owner, wid = env
    monkeypatch.setattr(get_settings(), "updater_secret_key", "any passphrase")
    assert client.put(url(wid), json=BODY, headers=H(owner)).json()["status"] == "active"
    with factory() as db:
        stored = db.execute(text("select secret_enc from affinebot_links")).scalar_one()
        assert stored.startswith("fernet:") and SECRET not in stored
        assert decrypt_secret(stored) == SECRET
        assert ab.client_for_workspace(db, wid)._secret == SECRET
    monkeypatch.setattr(get_settings(), "updater_secret_key", "")
    # without a key: plain prefix, and plain rows stay readable
    stored = encrypt_secret("s3")
    assert stored == "plain:s3" and decrypt_secret(stored) == "s3"


def test_client_for_workspace_not_linked(env) -> None:
    _, factory, _, wid = env
    with factory() as db, pytest.raises(ab.AffinebotError) as err:
        ab.client_for_workspace(db, wid)
    assert (err.value.status, err.value.detail) == (404, "affinebot_not_linked")


def test_client_error_mapping_and_methods(upstream) -> None:
    c = ab.AffinebotClient("https://bot.example.com/", CID, SECRET)
    assert c.health()["client"]["owner"] == "acme"
    for mode, status, detail in [("down", 502, "affinebot_unreachable"), ("401", 502, "affinebot_rejected"), ("500", 502, "affinebot_upstream")]:
        upstream.mode = mode
        with pytest.raises(ab.AffinebotError) as err:
            c.health()
        assert (err.value.status, err.value.detail) == (status, detail)
    upstream.mode = "429"
    with pytest.raises(ab.AffinebotError) as err:
        c.health()
    assert err.value.status == 429 and err.value.retry_after == "7"
    http = ab.http_error_for(err.value)
    assert http.status_code == 503 and http.headers == {"Retry-After": "7"}
    upstream.mode = "ok"
    with pytest.raises(ab.AffinebotError) as err:
        c.get_delegation("nope-missing") if False else c._request("GET", "/link/v1/unknown")
    assert (err.value.status, err.value.detail) == (404, "not_found")


def test_ttl_cache_hit_miss_and_invalidate(upstream, monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(ab._cache, "clock", lambda: now[0])
    c = ab.AffinebotClient("https://bot.example.com", CID, SECRET)

    def count(suffix):
        return sum(1 for r in upstream.calls if r.url.path.endswith(suffix))

    c.items("acme/web"); c.items("acme/web")
    assert count("/items") == 1
    c.items("acme/web", kind="pr")  # different key -> miss
    assert count("/items") == 2
    now[0] += 61
    c.items("acme/web")
    assert count("/items") == 3
    c.repos(); c.repos()
    assert count("/repos") == 1
    now[0] += 200  # repos TTL is 300s
    c.repos()
    assert count("/repos") == 1
    now[0] += 101
    c.repos()
    assert count("/repos") == 2
    ab.invalidate(CID)
    c.repos(); c.items("acme/web")
    assert count("/repos") == 3 and count("/items") == 4
    with pytest.raises(ab.AffinebotError):
        c.items("badrepo")
