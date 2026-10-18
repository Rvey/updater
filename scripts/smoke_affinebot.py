#!/usr/bin/env python3
"""Live cross-repo smoke test: updater <-> Affinebot over real HTTP (Shared contract v1).

Run with Affinebot's interpreter (needs fastapi, uvicorn, httpx, pyjwt/cryptography, and `affinebot` importable):

    cd /Users/redouane/Documents/GitHub/Affinebot && \
      uv run python /Users/redouane/Documents/ChatGPT/updater/scripts/smoke_affinebot.py

Starts: a fake GitHub API (in-process), Affinebot (GitHub App mode against the fake) and the updater
(temp SQLite), all on free 127.0.0.1 ports with temp dirs. Needs a local Redis on localhost:6379; it uses
DB number SMOKE_REDIS_DB (default 14), refuses to run if that DB is non-empty, and flushes it at the end.
Env overrides: UPDATER_DIR, AFFINEBOT_DIR, SMOKE_REDIS_DB.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Header, HTTPException, Request

HERE = Path(__file__).resolve().parent
UPDATER_DIR = Path(os.environ.get("UPDATER_DIR", HERE.parent))
AFFINEBOT_DIR = Path(os.environ.get("AFFINEBOT_DIR", "/Users/redouane/Documents/GitHub/Affinebot"))
REDIS_DB = int(os.environ.get("SMOKE_REDIS_DB", "14"))
OWNER, REPO = "acme", "widgets"
ADMIN_TOKEN = "smoke-admin-" + uuid.uuid4().hex
CB_SECRET = "smoke-callback-" + uuid.uuid4().hex

results: list[tuple[str, bool, str]] = []
procs: list[subprocess.Popen] = []


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def step(name: str, ok: bool, evidence: str) -> None:
    results.append((name, ok, evidence))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {evidence}", flush=True)
    if not ok:
        raise SystemExit(finish(1))


# ---------------------------------------------------------------- fake GitHub (App mode)
gh_log: list[str] = []
ISSUES = [
    {"number": 1, "title": "Login button broken", "body": "It 500s", "state": "open", "html_url": f"https://github.com/{OWNER}/{REPO}/issues/1",
     "user": {"login": "alice"}, "assignees": [{"login": "bob"}], "labels": [{"name": "bug"}], "comments": 2, "updated_at": "2026-01-02T00:00:00Z"},
    {"number": 2, "title": "Add dark mode", "body": "", "state": "open", "html_url": f"https://github.com/{OWNER}/{REPO}/issues/2",
     "user": {"login": "carol"}, "assignees": [], "labels": [], "comments": 0, "updated_at": "2026-01-01T00:00:00Z"},
    {"number": 3, "title": "Fix typo", "body": "pr", "state": "open", "html_url": f"https://github.com/{OWNER}/{REPO}/pull/3",
     "user": {"login": "dave"}, "assignees": [], "labels": [], "comments": 1, "updated_at": "2026-01-03T00:00:00Z",
     "pull_request": {"url": "x", "merged_at": None}, "draft": False},
]


def make_fake_github() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _log(request: Request, call_next):
        gh_log.append(f"{request.method} {request.url.path} auth={'yes' if request.headers.get('authorization') else 'no'}")
        return await call_next(request)

    @app.get("/users/{owner}/installation")
    def inst(owner: str):
        if owner.lower() != OWNER:
            raise HTTPException(404)
        return {"id": 4242}

    @app.get("/orgs/{owner}/installation")
    def org_inst(owner: str):
        raise HTTPException(404)

    @app.post("/app/installations/{iid}/access_tokens")
    def tok(iid: int):
        return {"token": "ghs_fake", "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}

    @app.get("/installation/repositories")
    def repos(authorization: str = Header(default="")):
        if authorization != "Bearer ghs_fake":
            raise HTTPException(401)
        return {"repositories": [{"full_name": f"{OWNER}/{REPO}", "private": True, "default_branch": "develop"}]}

    @app.get("/repos/{owner}/{name}")
    def repo(owner: str, name: str):
        if (owner.lower(), name.lower()) != (OWNER, REPO):
            raise HTTPException(404)
        return {"full_name": f"{owner}/{name}", "default_branch": "develop"}

    @app.get("/repos/{owner}/{name}/issues")
    def issues(owner: str, name: str, state: str = "open", per_page: int = 30, page: int = 1):
        if (owner.lower(), name.lower()) != (OWNER, REPO):
            raise HTTPException(404)
        rows = [i for i in ISSUES if state in ("all", i["state"])]
        return rows[(page - 1) * per_page: page * per_page]

    return app


class Server:
    def __init__(self, app, port):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("fake github did not start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(5)


# ---------------------------------------------------------------- process helpers
def spawn(cmd, env, cwd, logfile) -> subprocess.Popen:
    p = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=open(logfile, "w"), stderr=subprocess.STDOUT, start_new_session=True)
    procs.append(p)
    return p


def wait_http(url: str, proc: subprocess.Popen, logfile: Path, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            raise RuntimeError(f"process exited early:\n{logfile.read_text()[-2000:]}")
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            time.sleep(0.3)
    raise RuntimeError(f"timeout waiting for {url}:\n{logfile.read_text()[-2000:]}")


def redis_cli(*args) -> str:
    return subprocess.run(["redis-cli", "-n", str(REDIS_DB), *args], capture_output=True, text=True, timeout=10).stdout.strip()


def cleanup():
    for p in procs:
        if p.poll() is None:
            try:
                os.killpg(p.pid, 15)
            except ProcessLookupError:
                pass
    for p in procs:
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, 9)


def finish(code=0) -> int:
    print("\n==== SUMMARY ====")
    for n, ok, _ in results:
        print(f"{'PASS' if ok else 'FAIL'}  {n}")
    return code


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(CB_SECRET.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- main flow
def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-affinebot-"))
    fake: Server | None = None
    try:
        if redis_cli("ping") != "PONG":
            print("Redis not reachable on localhost:6379 (needed for arq enqueue)")
            return 2
        if redis_cli("dbsize").split()[-1] != "0":
            print(f"Redis DB {REDIS_DB} is not empty; set SMOKE_REDIS_DB to an empty db")
            return 2

        # fake GitHub + credentials
        gh_port, ab_port, up_port = free_port(), free_port(), free_port()
        fake = Server(make_fake_github(), gh_port)
        fake.start()
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        (tmp / "app.pem").write_bytes(pem)
        (tmp / "sa.json").write_text(json.dumps({
            "type": "service_account", "project_id": "smoke", "private_key_id": "k1", "private_key": pem.decode(),
            "client_email": "smoke@smoke.iam.gserviceaccount.com", "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token"}))

        ab_url, up_url = f"http://127.0.0.1:{ab_port}", f"http://127.0.0.1:{up_port}"
        base_env = {k: v for k, v in os.environ.items() if k not in ("UPDATER_TOKEN", "VIRTUAL_ENV")}
        ab_env = {**base_env,
                  "DATA_DIR": str(tmp / "ab-data"), "GITHUB_APP_ID": "12345", "GITHUB_APP_PRIVATE_KEY_FILE": str(tmp / "app.pem"),
                  "GITHUB_API_URL": f"http://127.0.0.1:{gh_port}", "GOOGLE_SERVICE_ACCOUNT_FILE": str(tmp / "sa.json"),
                  "REDIS_URL": f"redis://localhost:6379/{REDIS_DB}", "AFFINEBOT_ADMIN_TOKEN": ADMIN_TOKEN,
                  "UPDATER_CALLBACK_SECRET": CB_SECRET, "UPDATER_CALLBACK_ALLOWED_ORIGINS": up_url,
                  "ANTHROPIC_API_KEY": "sk-ant-smoke-not-real", "CHAT_VERIFY_REQUESTS": "true", "ALLOWED_REPO_OWNERS": ""}
        wd = tmp / "cwd"; wd.mkdir()  # cwd without a .env so repo .env files are not picked up
        spawn(["uv", "run", "--project", str(AFFINEBOT_DIR), "uvicorn", "affinebot.api:app", "--host", "127.0.0.1", "--port", str(ab_port)],
              ab_env, wd, tmp / "affinebot.log")
        up_env = {**base_env, "DATABASE_URL": f"sqlite:///{tmp}/updater.db", "AFFINEBOT_CALLBACK_SECRET": CB_SECRET,
                  "UPDATER_PUBLIC_URL": up_url, "AFFINEBOT_TIMEOUT_S": "10"}
        spawn(["uv", "run", "--project", str(UPDATER_DIR / "backend"), "uvicorn", "app.main:app", "--app-dir", str(UPDATER_DIR / "backend"), "--host", "127.0.0.1", "--port", str(up_port)],
              up_env, wd, tmp / "updater.log")
        wait_http(f"{ab_url}/healthz", procs[0], tmp / "affinebot.log")
        wait_http(f"{up_url}/api/health", procs[1], tmp / "updater.log")
        print(f"affinebot={ab_url} updater={up_url} github(fake)=127.0.0.1:{gh_port} tmp={tmp}")

        up = httpx.Client(base_url=up_url, timeout=30)
        adm = {"Authorization": f"Bearer {ADMIN_TOKEN}"}

        # 1 register
        email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
        r = up.post("/api/auth/register", json={"email": email, "password": "smoke-password-1"})
        step("1. register account", r.status_code == 201 and r.json().get("session_token", "").startswith("ups_"),
             f"POST /api/auth/register -> {r.status_code} email={r.json().get('email')}")
        up.headers["Authorization"] = f"Bearer {r.json()['session_token']}"

        # 2 workspaces
        r = up.get("/api/workspaces")
        wss = r.json()
        ok = r.status_code == 200 and len(wss) >= 1 and wss[0]["role"] == "owner" and wss[0]["projects"]
        step("2. GET /api/workspaces", ok, f"-> {r.status_code} {json.dumps(wss)[:300]}")
        wid, pid = wss[0]["id"], wss[0]["projects"][0]["id"]

        # 3 mint
        r = httpx.post(f"{ab_url}/link/admin/clients", headers=adm, json={"client_id": wid, "label": "smoke", "owner": OWNER})
        j = r.json() if r.status_code == 201 else {}
        step("3. mint link client (Affinebot admin API)",
             r.status_code == 201 and j.get("client_id") == wid and j.get("token", "").startswith("abl_") and j.get("installation_id") == 4242,
             f"POST /link/admin/clients -> {r.status_code} client_id==workspace_id:{j.get('client_id') == wid} installation_id={j.get('installation_id')} owner={j.get('owner')} (body: {r.text[:200] if r.status_code != 201 else 'token redacted'})")
        token = j["token"]
        bad = httpx.post(f"{ab_url}/link/admin/clients", headers={"Authorization": "Bearer nope"}, json={"label": "x", "owner": OWNER})
        step("3b. admin auth rejects wrong token", bad.status_code == 401 and bad.json() == {"detail": "unauthorized"}, f"-> {bad.status_code} {bad.text}")

        # 4 PUT link
        r = up.put(f"/api/workspaces/{wid}/affinebot", json={"base_url": ab_url, "client_id": wid, "secret": token})
        j = r.json()
        step("4. PUT /api/workspaces/{id}/affinebot -> active",
             r.status_code == 200 and j.get("status") == "active" and j.get("github_owner") == OWNER and j.get("installation_id") == 4242 and "secret" not in json.dumps(j) and token not in r.text,
             f"-> {r.status_code} {json.dumps(j)}")
        r = up.post(f"/api/workspaces/{wid}/affinebot/check")
        step("4b. POST .../affinebot/check", r.status_code == 200 and r.json()["status"] == "active", f"-> {r.status_code} status={r.json().get('status')}")
        h = httpx.get(f"{ab_url}/link/v1/health", headers={"Authorization": f"Bearer {token}", "X-Link-Client": wid}).json()
        step("4c. Affinebot /link/v1/health shape", h.get("ok") is True and h.get("redis") is True and h.get("db") is True and h["client"]["client_id"] == wid,
             json.dumps(h))
        r401 = httpx.get(f"{ab_url}/link/v1/health", headers={"Authorization": "Bearer abl_wrong", "X-Link-Client": wid})
        step("4d. wrong runtime token -> 401 unauthorized", r401.status_code == 401 and r401.json() == {"detail": "unauthorized"}, f"-> {r401.status_code} {r401.text}")

        # 5 repos + items
        r = up.get(f"/api/workspaces/{wid}/github/repos")
        step("5a. GET github/repos", r.status_code == 200 and r.json() == [{"full_name": f"{OWNER}/{REPO}", "private": True, "default_branch": "develop", "linked": False, "project_id": None}],
             f"-> {r.status_code} {r.text}")
        r = up.get(f"/api/workspaces/{wid}/github/items", params={"repo": f"{OWNER}/{REPO}"})
        items = r.json().get("items", []) if r.status_code == 200 else []
        step("5b. GET github/items", r.status_code == 200 and sorted(i["number"] for i in items) == [1, 2, 3] and {i["number"]: i["is_pr"] for i in items} == {1: False, 2: False, 3: True}
             and all("task_id" in i for i in items), f"-> {r.status_code} numbers={[ (i['number'], i['is_pr']) for i in items]} next_page={r.json().get('next_page')}")

        # 6 sync
        r = up.post("/api/github/sync", json={"project_id": pid, "repo": f"{OWNER}/{REPO}", "state": "open", "numbers": [1, 3]})
        step("6. POST /api/github/sync numbers=[1,3]", r.status_code == 200 and r.json()["total"] == 2 and r.json()["created"] == 2,
             f"-> {r.status_code} {r.text}")
        tasks = [t for t in up.get("/api/tasks", params={"project_id": pid}).json() if (t.get("external_id") or "").startswith("github:")]
        t1 = next((t for t in tasks if t["external_id"].endswith("#1")), None)
        step("6b. synced tasks exist", t1 is not None and len(tasks) == 2, f"external_ids={[t['external_id'] for t in tasks]} status(#1)={t1 and t1['status']}")

        # 7 delegate
        r = up.post(f"/api/tasks/{t1['id']}/delegate", json={"instruction": "please fix", "base_branch": "develop"})
        d = r.json()
        step("7. POST /api/tasks/{id}/delegate -> queued on Affinebot",
             r.status_code == 201 and d.get("status") == "queued" and d.get("repo") == f"{OWNER}/{REPO}" and d.get("issue_number") == 1,
             f"-> {r.status_code} {json.dumps(d)}")
        did = d["id"]
        # find the remote id from Affinebot's store (updater DelegationRead does not expose it)
        from affinebot.config import Settings
        from affinebot.delegation import post_callback
        from affinebot.store import Store
        store = Store(tmp / "ab-data" / "affinebot.db")
        ref = store.get_job_result(f"delegation-ref:{wid}:{did}")
        rec = store.get_job_result(f"delegation:{ref['remote_id']}") if ref else None
        expected_cb = f"{up_url}/api/delegations/{did}/status"
        step("7b. Affinebot stored delegation with contract callback_url", bool(rec) and rec["callback_url"] == expected_cb and rec["status"] == "queued",
             f"remote_id={ref and ref['remote_id']} callback_url={rec and rec['callback_url']} (expected {expected_cb})")
        remote_id = ref["remote_id"]
        g = httpx.get(f"{ab_url}/link/v1/delegations/{remote_id}", headers={"Authorization": f"Bearer {token}", "X-Link-Client": wid}).json()
        step("7c. GET /link/v1/delegations/{remote_id} shape", set(g) == {"status", "branch", "pr_url", "pr_number", "error", "summary"} and g["status"] == "queued", json.dumps(g))
        step("7d. job enqueued in Redis (arq)", redis_cli("dbsize").split()[-1] != "0", f"redis db{REDIS_DB} dbsize={redis_cli('dbsize')} keys={redis_cli('keys', '*').replace(chr(10), ' ')[:200]}")
        # idempotency: same delegation_id again -> same remote_id
        again = httpx.post(f"{ab_url}/link/v1/delegations", headers={"Authorization": f"Bearer {token}", "X-Link-Client": wid}, json={
            "delegation_id": did, "repo": f"{OWNER}/{REPO}", "issue_number": 1, "title": "t", "instruction": "i", "base_branch": None, "callback_url": expected_cb})
        step("7e. POST delegations idempotent on delegation_id", again.status_code == 202 and again.json()["remote_id"] == remote_id, f"-> {again.status_code} {again.text}")

        # 8 callbacks
        settings = Settings(_env_file=None, updater_callback_secret=CB_SECRET, updater_callback_allowed_origins=up_url)
        ok = asyncio.run(post_callback(settings, rec, {"status": "running"}))
        d = up.get(f"/api/delegations/{did}").json()
        step("8a. Affinebot post_callback(running) -> updater", ok and d["status"] == "running", f"post_callback returned {ok}; updater delegation status={d['status']}")
        pr_url = f"https://github.com/{OWNER}/{REPO}/pull/77"
        ok = asyncio.run(post_callback(settings, rec, {"status": "pr_opened", "branch": f"affinebot/claude-{remote_id[:8]}", "pr_url": pr_url, "pr_number": 77, "summary": "Fixed login"}))
        d = up.get(f"/api/delegations/{did}").json()
        task = up.get(f"/api/tasks/{t1['id']}").json()
        step("8b. Affinebot post_callback(pr_opened) -> delegation pr_opened, task -> review",
             ok and d["status"] == "pr_opened" and d["pr_url"] == pr_url and d["pr_number"] == 77 and task["status"] == "review",
             f"post_callback={ok}; delegation={json.dumps({k: d[k] for k in ('status', 'branch', 'pr_url', 'pr_number', 'summary')})}; task.status={task['status']} tags={task.get('tags')}")
        # negative wire checks
        body = json.dumps({"status": "failed", "error": "late"}).encode()
        r = httpx.post(expected_cb, content=body, headers={"X-Affinebot-Signature": "sha256=" + "0" * 64, "Content-Type": "application/json"})
        step("8c. bad signature -> 401", r.status_code == 401, f"-> {r.status_code} {r.text}")
        r = httpx.post(expected_cb, content=body, headers={"X-Affinebot-Signature": sign(body), "Content-Type": "application/json"})
        d = up.get(f"/api/delegations/{did}").json()
        step("8d. late 'failed' after pr_opened ignored with 200", r.status_code == 200 and d["status"] == "pr_opened", f"-> {r.status_code}; status stays {d['status']}")
        bad_pr = json.dumps({"status": "pr_opened", "pr_url": "https://github.com/evil/other/pull/1"}).encode()
        r = httpx.post(f"{up_url}/api/delegations/{did}/status", content=bad_pr, headers={"X-Affinebot-Signature": sign(bad_pr), "Content-Type": "application/json"})
        step("8e. foreign pr_url -> 422", r.status_code == 422, f"-> {r.status_code} {r.text}")
        unk = json.dumps({"status": "running"}).encode()
        r = httpx.post(f"{up_url}/api/delegations/{uuid.uuid4()}/status", content=unk, headers={"X-Affinebot-Signature": sign(unk), "Content-Type": "application/json"})
        step("8f. unknown delegation id -> 404", r.status_code == 404, f"-> {r.status_code}")
        step("fake GitHub saw App-auth flow", any("access_tokens" in l for l in gh_log) and any("installation/repositories" in l for l in gh_log) and any("/issues" in l for l in gh_log),
             f"{len(gh_log)} requests, distinct: {sorted(set(gh_log))}")
        return finish(0)
    finally:
        cleanup()
        if fake:
            fake.stop()
        try:
            redis_cli("flushdb")
        except Exception:
            pass
        if os.environ.get("SMOKE_KEEP_TMP"):
            print("kept", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
