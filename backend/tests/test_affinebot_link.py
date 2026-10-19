"""Affinebot link: client (MockTransport), secret box, TTL cache and the /affinebot routes."""
import json

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
        self.mint_status = 201
        self.mint_detail = ""
        self.revoke_status = 204
        self.minted = 0

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
        if path == "/link/admin/owners":
            return httpx.Response(200, json={"owners": [
                {"owner": "acme", "installation_id": 42, "installed": True},
                {"owner": "other-org", "installation_id": None, "installed": False}]})
        if path == "/link/admin/clients" and request.method == "POST":
            if self.mint_status != 201:
                return httpx.Response(self.mint_status, json={"detail": self.mint_detail})
            self.minted += 1
            body = json.loads(request.content)
            return httpx.Response(201, json={"client_id": body["client_id"], "token": f"abl_minted{self.minted}",
                                             "owner": body["owner"], "installation_id": 42})
        if path.startswith("/link/admin/clients/") and request.method == "DELETE":
            return httpx.Response(self.revoke_status, json={"detail": "x"} if self.revoke_status != 204 else None)
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


# --- managed mode ------------------------------------------------------------------------

ADMIN = "adm_topsecretadmintoken"


@pytest.fixture
def managed(monkeypatch):
    monkeypatch.setattr(get_settings(), "affinebot_url", "https://bot.example.com/")
    monkeypatch.setattr(get_settings(), "affinebot_admin_token", ADMIN)


def _admin_calls(upstream, method=None):
    return [c for c in upstream.calls if c.url.path.startswith("/link/admin") and (method is None or c.method == method)]


def test_config_not_managed(env, upstream) -> None:
    client, _, owner, _ = env
    res = client.get("/api/affinebot/config", headers=H(owner))
    assert res.status_code == 200 and res.json() == {"managed": False, "base_url": None, "owners": []}
    assert not upstream.calls
    assert client.get("/api/affinebot/config").status_code == 401


def test_config_managed_lists_owners_cached(env, upstream, managed) -> None:
    client, _, owner, _ = env
    res = client.get("/api/affinebot/config", headers=H(owner))
    assert res.json() == {"managed": True, "base_url": "https://bot.example.com",
                          "owners": [{"owner": "acme", "installed": True}, {"owner": "other-org", "installed": False}]}
    assert ADMIN not in res.text
    assert _admin_calls(upstream)[0].headers["authorization"] == f"Bearer {ADMIN}"
    client.get("/api/affinebot/config", headers=H(owner))
    assert len(_admin_calls(upstream, "GET")) == 1  # cached


def test_config_managed_unreachable(env, upstream, managed) -> None:
    client, _, owner, _ = env
    upstream.mode = "down"
    res = client.get("/api/affinebot/config", headers=H(owner))
    assert res.status_code == 200
    assert res.json() == {"managed": True, "base_url": "https://bot.example.com", "owners": [], "error": "affinebot_unreachable"}
    assert ADMIN not in res.text


def test_connect_happy_path(env, upstream, managed) -> None:
    client, factory, owner, wid = env
    res = client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H(owner))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "active" and data["github_owner"] == "acme" and data["installation_id"] == 42
    assert data["client_id"] == wid and data["base_url"] == "https://bot.example.com"
    assert "abl_minted1" not in res.text and ADMIN not in res.text
    mint = json.loads(_admin_calls(upstream, "POST")[0].content)
    assert mint["client_id"] == wid and mint["owner"] == "acme" and mint["rotate"] is True and mint["label"].startswith("updater:")
    with factory() as db:
        stored = db.execute(text("select secret_enc from affinebot_links")).scalar_one()
        assert "abl_minted1" not in stored.split(":", 1)[0] and decrypt_secret(stored) == "abl_minted1"
    health = [c for c in upstream.calls if c.url.path == "/link/v1/health"][-1]
    assert health.headers["authorization"] == "Bearer abl_minted1" and health.headers["x-link-client"] == wid
    assert "abl_minted1" not in client.get(url(wid), headers=H(owner)).text


def test_connect_member_forbidden_and_stranger(env, upstream, managed) -> None:
    client, _, owner, wid = env
    member = _register_account(client, "member@example.com")
    assert client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H(member)).status_code == 404
    invite = client.post(f"/api/workspaces/{wid}/invites", json={"email": "member@example.com"}, headers=H(owner)).json()
    assert client.post("/api/invites/accept", json={"token": invite["token"]}, headers=H(member)).status_code == 200
    assert client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H(member)).status_code == 403
    assert not _admin_calls(upstream, "POST")


def test_connect_env_token_forbidden(env, managed, monkeypatch) -> None:
    client, _, _, wid = env
    monkeypatch.setattr(get_settings(), "updater_token", "shared-secret")
    assert client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H("shared-secret")).status_code == 403


def test_connect_not_managed(env, upstream) -> None:
    client, _, owner, wid = env
    res = client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H(owner))
    assert res.status_code == 409 and res.json() == {"detail": "affinebot_not_managed"}
    assert not upstream.calls


def test_connect_rejected_owner(env, upstream, managed) -> None:
    client, _, owner, wid = env
    upstream.mint_status, upstream.mint_detail = 403, "owner_not_allowed"
    res = client.post(url(wid, "/connect"), json={"owner": "evil"}, headers=H(owner))
    assert res.status_code == 403 and res.json() == {"detail": "owner_not_allowed"} and ADMIN not in res.text
    upstream.mint_status, upstream.mint_detail = 404, "github_app_not_installed"
    res = client.post(url(wid, "/connect"), json={"owner": "other-org"}, headers=H(owner))
    assert res.status_code == 422 and res.json() == {"detail": "github_app_not_installed"}
    assert client.get(url(wid), headers=H(owner)).status_code == 404  # nothing stored
    upstream.mint_status = 401
    res = client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H(owner))
    assert res.status_code == 502 and ADMIN not in res.text
    upstream.mode = "down"
    res = client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H(owner))
    assert res.status_code == 502 and res.json() == {"detail": "affinebot_unreachable"}


def test_reconnect_rotates_credential(env, upstream, managed) -> None:
    client, factory, owner, wid = env
    assert client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H(owner)).status_code == 200
    assert client.post(url(wid, "/connect"), json={"owner": "other-org"}, headers=H(owner)).status_code == 200
    with factory() as db:
        assert db.query(AffinebotLink).count() == 1
        assert ab.client_for_workspace(db, wid)._secret == "abl_minted2"
    assert [json.loads(c.content)["owner"] for c in _admin_calls(upstream, "POST")] == ["acme", "other-org"]
    health = [c for c in upstream.calls if c.url.path == "/link/v1/health"][-1]
    assert health.headers["authorization"] == "Bearer abl_minted2"


def test_disconnect_revokes_in_managed_mode(env, upstream, managed) -> None:
    client, factory, owner, wid = env
    client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H(owner))
    assert client.delete(url(wid), headers=H(owner)).status_code == 204
    revokes = _admin_calls(upstream, "DELETE")
    assert len(revokes) == 1 and revokes[0].url.path == f"/link/admin/clients/{wid}"
    assert revokes[0].headers["authorization"] == f"Bearer {ADMIN}"
    assert client.get(url(wid), headers=H(owner)).status_code == 404


@pytest.mark.parametrize("failure", ["down", "404", "500"])
def test_disconnect_survives_revoke_failure(env, upstream, managed, failure) -> None:
    client, factory, owner, wid = env
    client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H(owner))
    if failure == "down":
        upstream.mode = "down"
    else:
        upstream.revoke_status = int(failure)
    assert client.delete(url(wid), headers=H(owner)).status_code == 204
    with factory() as db:
        assert db.query(AffinebotLink).count() == 0


def test_disconnect_not_managed_does_not_call_admin(env, upstream) -> None:
    client, _, owner, wid = env
    client.put(url(wid), json=BODY, headers=H(owner))
    assert client.delete(url(wid), headers=H(owner)).status_code == 204
    assert not _admin_calls(upstream)


def test_admin_token_never_in_bodies(env, upstream, managed) -> None:
    client, _, owner, wid = env
    responses = [
        client.get("/api/affinebot/config", headers=H(owner)),
        client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H(owner)),
        client.get(url(wid), headers=H(owner)),
        client.post(url(wid, "/check"), headers=H(owner)),
    ]
    upstream.mode = "401"
    ab._cache.clear()
    responses += [client.get("/api/affinebot/config", headers=H(owner)),
                  client.post(url(wid, "/connect"), json={"owner": "acme"}, headers=H(owner)),
                  client.post(url(wid, "/check"), headers=H(owner))]
    upstream.mode = "ok"
    responses.append(client.delete(url(wid), headers=H(owner)))
    for res in responses:
        assert ADMIN not in res.text and ADMIN not in str(res.headers)
