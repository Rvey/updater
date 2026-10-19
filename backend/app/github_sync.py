"""GitHub item model and parsing shared by the Affinebot-sourced sync and the webhook."""
import hashlib
import hmac
import re
from dataclasses import dataclass, field


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


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def items_from_affinebot(repo: str, raw: list[dict]) -> list[GitHubItem]:
    """Map Affinebot /link/v1 item rows (shared contract v1) to GitHubItem. ``repo`` is owner/name."""
    full_name = repo.lower()
    items: list[GitHubItem] = []
    for row in raw:
        number = row.get("number")
        if not isinstance(number, int):
            continue
        is_pr = bool(row.get("is_pr"))
        assignees = row.get("assignees") or []
        items.append(
            GitHubItem(
                external_id=f"github:{full_name}#{number}",
                url=row.get("url") or "",
                title=row.get("title") or f"{'pr' if is_pr else 'issue'} #{number}",
                body=row.get("body") or "",
                is_pr=is_pr,
                state="closed" if row.get("state") == "closed" else "open",
                merged=bool(row.get("merged")),
                draft=bool(row.get("draft")),
                labels=[str(label) for label in (row.get("labels") or [])],
                assignee=assignees[0] if assignees else None,
                branch=row.get("branch"),
            )
        )
    return items


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
