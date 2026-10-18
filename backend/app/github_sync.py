"""One-way import of GitHub issues and pull requests, authenticated with a personal access token."""
import hashlib
import hmac
import re
from dataclasses import dataclass, field

import httpx

API_ROOT = "https://api.github.com"
PAGE_SIZE = 100
MAX_PAGES = 5

_REPO_RE = re.compile(r"^(?:https?://github\.com/|git@github\.com:|github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", re.I)


class GitHubSyncError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class GitHubItem:
    external_id: str
    url: str
    title: str
    body: str
    is_pr: bool
    state: str  # "open" | "closed"
    merged: bool
    draft: bool
    labels: list[str] = field(default_factory=list)
    assignee: str | None = None
    branch: str | None = None


def parse_repo(value: str) -> tuple[str, str]:
    match = _REPO_RE.match((value or "").strip())
    if not match:
        raise GitHubSyncError("Repository must look like owner/name or a github.com URL", 422)
    return match.group(1), match.group(2)


def fetch_items(owner: str, repo: str, token: str, state: str = "open", include_prs: bool = True, include_issues: bool = True, client: httpx.Client | None = None) -> list[GitHubItem]:
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "updater-sync",
    }
    own_client = client is None
    http = client or httpx.Client(timeout=20)
    items: list[GitHubItem] = []
    try:
        for page in range(1, MAX_PAGES + 1):
            try:
                response = http.get(
                    f"{API_ROOT}/repos/{owner}/{repo}/issues",
                    headers=headers,
                    params={"state": state, "per_page": PAGE_SIZE, "page": page, "sort": "updated"},
                )
            except httpx.HTTPError as exc:
                raise GitHubSyncError("Could not reach GitHub: " + exc.__class__.__name__) from exc
            if response.status_code == 401:
                raise GitHubSyncError("GitHub rejected the token", 401)
            if response.status_code in (403, 429):
                raise GitHubSyncError("GitHub denied the request (token scope or rate limit)", 403)
            if response.status_code == 404:
                raise GitHubSyncError("Repository not found, or the token cannot see it", 404)
            if response.status_code != 200:
                raise GitHubSyncError(f"GitHub returned {response.status_code}")
            rows = response.json()
            for row in rows:
                is_pr = "pull_request" in row
                if (is_pr and not include_prs) or (not is_pr and not include_issues):
                    continue
                pr_info = row.get("pull_request") or {}
                kind = "pr" if is_pr else "issue"
                items.append(
                    GitHubItem(
                        external_id=f"github:{owner}/{repo}#{row['number']}".lower(),
                        url=row.get("html_url") or "",
                        title=row.get("title") or f"{kind} #{row['number']}",
                        body=row.get("body") or "",
                        is_pr=is_pr,
                        state=row.get("state") or "open",
                        merged=bool(pr_info.get("merged_at")),
                        draft=bool(row.get("draft")),
                        labels=[(label.get("name") if isinstance(label, dict) else str(label)) for label in row.get("labels", [])],
                        assignee=(row.get("assignee") or {}).get("login"),
                    )
                )
            if len(rows) < PAGE_SIZE:
                break
    finally:
        if own_client:
            http.close()
    return items


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def verify_repo_access(owner: str, repo: str, token: str, client: httpx.Client | None = None) -> None:
    """Prove the token holder can read the repo, so one account cannot claim another's private repo."""
    http = client or httpx.Client(timeout=20)
    try:
        response = http.get(
            f"{API_ROOT}/repos/{owner}/{repo}",
            headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "User-Agent": "updater-sync"},
        )
    except httpx.HTTPError as exc:
        raise GitHubSyncError("Could not reach GitHub: " + exc.__class__.__name__) from exc
    finally:
        if client is None:
            http.close()
    if response.status_code == 401:
        raise GitHubSyncError("GitHub rejected the token", 401)
    if response.status_code in (403, 404):
        raise GitHubSyncError("Repository not found, or the token cannot see it", 404)
    if response.status_code != 200:
        raise GitHubSyncError(f"GitHub returned {response.status_code}")


def item_from_webhook(event: str, payload: dict) -> tuple[str, GitHubItem] | None:
    """Return (owner/repo, item) for an issues or pull_request event, else None."""
    full_name = ((payload.get("repository") or {}).get("full_name") or "").lower()
    if event == "issues":
        row, is_pr = payload.get("issue"), False
    elif event == "pull_request":
        row, is_pr = payload.get("pull_request"), True
    else:
        return None
    if not row or not full_name:
        return None
    return full_name, GitHubItem(
        external_id=f"github:{full_name}#{row['number']}",
        url=row.get("html_url") or "",
        title=row.get("title") or f"#{row['number']}",
        body=row.get("body") or "",
        is_pr=is_pr,
        state=row.get("state") or "open",
        merged=bool(row.get("merged") or row.get("merged_at")),
        draft=bool(row.get("draft")),
        labels=[label.get("name", "") for label in row.get("labels", []) if isinstance(label, dict)],
        assignee=(row.get("assignee") or {}).get("login"),
    )
