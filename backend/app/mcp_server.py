"""Agent-facing MCP server. Run with `uv run python -m app.mcp_server`."""

from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .config import get_settings


async def api_request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    settings = get_settings()
    base_url = settings.updater_api_url.rstrip("/")
    token = settings.updater_token
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, f"{base_url}{path}", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as err:
        raise RuntimeError(f"Updater API rejected the request ({err.response.status_code}): {err.response.text}") from err
    except httpx.RequestError as err:
        raise RuntimeError(f"Cannot reach Updater API at {base_url}: {err}") from err


async def publish_feature(
    title: str,
    summary: str,
    repo_url: str,
    why: str,
    how_it_works: str,
    impact: str,
    files_changed: list[str],
    tags: list[str],
    branch: str = "",
    commit_sha: str = "",
    pr_url: str = "",
    tradeoffs: str = "",
    learning_notes: str = "",
    author_agent: str = "",
    external_id: str = "",
) -> dict[str, Any]:
    """Record a shipped feature with its code context and learning notes.

    Call only after implementation and verification. The repo_url must be a reachable repository URL.
    Set external_id to a stable value such as `owner/repo:commit-sha:feature-slug` to avoid duplicates.
    learning_notes should teach the owner the key code path in plain language.
    """
    result = await api_request(
        "POST",
        "/api/updates",
        {
            "title": title,
            "summary": summary,
            "repo_url": repo_url,
            "why": why,
            "how_it_works": how_it_works,
            "impact": impact,
            "files_changed": files_changed,
            "tags": tags,
            "branch": branch or None,
            "commit_sha": commit_sha or None,
            "pr_url": pr_url or None,
            "tradeoffs": tradeoffs,
            "learning_notes": learning_notes,
            "author_agent": author_agent or None,
            "external_id": external_id or None,
        },
    )
    return {"id": result["id"], "title": result["title"], "repo_url": result["repo_url"]}


async def list_feature_updates(query: str = "") -> list[dict[str, Any]]:
    """Search recorded feature updates by title, summary, reason or implementation."""
    from urllib.parse import urlencode

    result = await api_request("GET", f"/api/updates?{urlencode({'q': query})}")
    return [
        {"id": item["id"], "title": item["title"], "summary": item["summary"], "repo_url": item["repo_url"], "shipped_at": item["shipped_at"]}
        for item in result
    ]


async def get_feature_update(update_id: str) -> dict[str, Any]:
    """Read the saved context and previous questions for one shipped feature."""
    return await api_request("GET", f"/api/updates/{update_id}")


async def add_feature_impact(update_id: str, observation: str) -> dict[str, Any]:
    """Record a dated outcome observed after a feature shipped. Use measured facts when available."""
    return await api_request("POST", f"/api/updates/{update_id}/impact-notes", {"note": observation})


def create_mcp_server() -> FastMCP:
    """Create a fresh server because the HTTP session manager has a single lifespan."""
    settings = get_settings()
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_hosts.extend(host.strip() for host in settings.mcp_allowed_hosts.split(",") if host.strip())
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    allowed_origins.extend(origin.strip() for origin in settings.cors_origins.split(",") if origin.strip())
    server = FastMCP(
        "Updater",
        instructions=(
            "Publish a feature update after a feature has actually shipped. Capture the user's reason, "
            "the real implementation, expected impact, tradeoffs, changed files and repository link. "
            "Use facts from the code and task; never invent details."
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )
    for tool in (publish_feature, list_feature_updates, get_feature_update, add_feature_impact):
        server.add_tool(tool)
    return server


server = create_mcp_server()


if __name__ == "__main__":
    server.run(transport="stdio")
