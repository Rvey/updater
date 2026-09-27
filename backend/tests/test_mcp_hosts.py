from fastapi.testclient import TestClient

from app import main


def _init_payload(n=1):
    return {
        "jsonrpc": "2.0",
        "id": n,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "updater-test", "version": "1"},
        },
    }


def test_public_hostname_accepted_with_and_without_port(monkeypatch):
    monkeypatch.setattr(main.settings, "mcp_allowed_hosts", "updaterapi.blitzgo.io")
    monkeypatch.setattr(main.settings, "updater_api_url", "http://127.0.0.1:8000")
    monkeypatch.setattr(main.settings, "updater_token", "")
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(main.app, base_url="https://updaterapi.blitzgo.io") as client:
        response = client.post("/mcp", headers=headers, json=_init_payload(1))
        assert response.status_code == 200, response.text
    with TestClient(main.app, base_url="https://updaterapi.blitzgo.io:8000") as client:
        response = client.post("/mcp", headers=headers, json=_init_payload(1))
        assert response.status_code == 200, response.text


def test_api_url_fallback_covers_public_hostname(monkeypatch):
    monkeypatch.setattr(main.settings, "mcp_allowed_hosts", "")
    monkeypatch.setattr(main.settings, "updater_api_url", "https://updaterapi.blitzgo.io")
    monkeypatch.setattr(main.settings, "updater_token", "")
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(main.app, base_url="https://updaterapi.blitzgo.io") as client:
        response = client.post("/mcp", headers=headers, json=_init_payload(1))
        assert response.status_code == 200, response.text
