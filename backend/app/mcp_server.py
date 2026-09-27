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
    code_context: list[dict[str, Any]] | None = None,
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
    code_context is an optional list of {path, content, start_line, end_line} excerpts read from the
    local codebase — attach the 1-5 focused snippets that explain the change so Updater can answer
    follow-up questions without further file access.
    """
    if code_context is None:
        code_context = []
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
            "code_context": code_context,
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


async def list_context_requests(status: str = "pending", repo: str = "") -> list[dict[str, Any]]:
    """List code-context requests waiting for a connected agent.

    Poll this when working inside a project checkout: each request names the update and the question
    the owner asked. Read the needed files from the local codebase, then answer with
    fulfill_context_request using short excerpts (path, content, start_line, end_line).
    The app only receives the excerpts you send — never full repo access.
    """
    from urllib.parse import urlencode

    result = await api_request("GET", f"/api/context-requests?{urlencode({'status': status, 'repo': repo})}")
    return result


async def fulfill_context_request(request_id: str, excerpts: list[dict[str, Any]]) -> dict[str, Any]:
    """Send back code excerpts for a context request.

    Keep excerpts minimal: only the functions or hunks needed to answer the question
    (max 8 files, ~6000 chars each). They are stored on the update and used for follow-up Q&A.
    """
    return await api_request("POST", f"/api/context-requests/{request_id}/fulfill", {"excerpts": excerpts})


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


def _expand_allowed_hosts(entries: list[str]) -> list[str]:
    """Expand bare hostnames so both `host` and `host:*` match.

    The MCP SDK validates the Host header by exact match, except for
    trailing `:*` wildcard-port entries. A reverse proxy (Cloudflare,
    Dokploy) typically forwards `Host: public.example.com` with no port
    for 443, while direct access may include one (`host:8000`). Accept
    both forms for every configured hostname so operators only need to
    list the bare hostname.
    """
    seen: set[str] = set()
    expanded: list[str] = []
    for entry in entries:
        entry = entry.strip()
        if not entry or entry in seen:
            continue
        seen.add(entry)
        expanded.append(entry)
        if ":" not in entry:
            wildcard = f"{entry}:*"
            if wildcard not in seen:
                seen.add(wildcard)
                expanded.append(wildcard)
    return expanded


def _api_url_hosts(api_url: str) -> list[str]:
    """Derive candidate Host entries from UPDATER_API_URL as a fallback."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(api_url.strip())
    except Exception:
        return []
    host = (parsed.hostname or "").strip()
    if not host or host in {"127.0.0.1", "localhost", "::1"}:
        return []
    hosts = [host]
    if parsed.port:
        hosts.append(f"{host}:{parsed.port}")
    return hosts


def create_mcp_server() -> FastMCP:
    """Create a fresh server because the HTTP session manager has a single lifespan."""
    settings = get_settings()
    configured = [host.strip() for host in settings.mcp_allowed_hosts.split(",") if host.strip()]
    configured.extend(_api_url_hosts(settings.updater_api_url))
    allowed_hosts = _expand_allowed_hosts(["127.0.0.1:*", "localhost:*", "[::1]:*"] + configured)
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    allowed_origins.extend(origin.strip() for origin in settings.cors_origins.split(",") if origin.strip())
    server = FastMCP(
        "Updater",
        instructions=(
            "Publish a feature update after a feature has actually shipped. Capture the user's reason, "
            "the real implementation, expected impact, tradeoffs, changed files and repository link. "
            "Use facts from the code and task; never invent details. "
            "You are also the codebase proxy: poll list_context_requests for this repo and fulfill "
            "pending questions with short local file excerpts."
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
    for tool in (publish_feature, list_feature_updates, get_feature_update, add_feature_impact, list_context_requests, fulfill_context_request):
        server.add_tool(tool)
    return server


server = create_mcp_server()


if __name__ == "__main__":
    server.run(transport="stdio")
