import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  GitPullRequest,
  Github,
  CircleDot,
  Loader2,
  Lock,
  MessageSquare,
  RefreshCw,
  Search,
} from "lucide-react";
import { ApiError, request as api } from "./lib/api";
import type {
  GitHubItem,
  GitHubItemsPage,
  GitHubRepo,
  GitHubSyncResult,
} from "./types";
import { Button } from "./components/ui/button";
import "./tasks.css";
import "./github.css";

type Kind = "all" | "issue" | "pr";
type State = "open" | "closed" | "all";

function errorState(err: unknown): { notLinked: boolean; message: string } {
  if (err instanceof ApiError) {
    if (err.detail === "affinebot_not_linked")
      return { notLinked: true, message: "" };
    if (err.detail === "affinebot_unreachable" || err.status === 502 || err.status === 503)
      return {
        notLinked: false,
        message:
          "Could not reach Affinebot right now. Try again in a moment, or check the link in Settings > Integrations.",
      };
    if (err.detail === "affinebot_rejected")
      return {
        notLinked: false,
        message:
          "Affinebot rejected this workspace's credentials. Re-link it in Settings > Integrations.",
      };
    return { notLinked: false, message: err.message };
  }
  return { notLinked: false, message: err instanceof Error ? err.message : "Request failed" };
}

function ago(value: string): string {
  const diff = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(diff)) return "";
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return m + "m ago";
  const h = Math.floor(m / 60);
  if (h < 24) return h + "h ago";
  const d = Math.floor(h / 24);
  if (d < 30) return d + "d ago";
  return new Date(value).toLocaleDateString();
}

function itemState(item: GitHubItem): { label: string; cls: string } {
  if (item.is_pr && item.merged) return { label: "Merged", cls: "merged" };
  if (item.is_pr && item.draft) return { label: "Draft", cls: "draft" };
  return item.state === "open"
    ? { label: "Open", cls: "open" }
    : { label: "Closed", cls: "closed" };
}

export function GitHubItemRow({
  item,
  canImport,
  importing,
  onImport,
  onOpenTask,
  actions,
}: {
  item: GitHubItem;
  canImport: boolean;
  importing: boolean;
  onImport: (item: GitHubItem) => void;
  onOpenTask?: (taskId: string) => void;
  /** Slot for extra per-item actions (e.g. the "Delegate to Claude Code" button added by the next phase). */
  actions?: ReactNode;
}) {
  const st = itemState(item);
  const Icon = item.is_pr ? GitPullRequest : CircleDot;
  return (
    <li className="gh-row">
      <Icon size={16} className={"gh-kind " + st.cls} aria-hidden />
      <div className="gh-main">
        <div className="gh-title">
          <a href={item.url} target="_blank" rel="noreferrer">
            {item.title} <ArrowUpRight size={12} />
          </a>
          <span className={"gh-state " + st.cls}>{st.label}</span>
        </div>
        <div className="gh-meta">
          <span>#{item.number}</span>
          {item.author && <span>by {item.author}</span>}
          <span>updated {ago(item.updated_at)}</span>
          {item.comments > 0 && (
            <span className="gh-inline">
              <MessageSquare size={11} /> {item.comments}
            </span>
          )}
          {item.branch && <code>{item.branch}</code>}
        </div>
        {item.labels.length > 0 && (
          <div className="gh-labels">
            {item.labels.map((label) => (
              <span key={label} className="tk-chip">
                {label}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="gh-actions" data-slot="item-actions">
        {actions}
        {item.task_id ? (
          <button
            type="button"
            className="tk-btn gh-imported"
            onClick={() => onOpenTask?.(item.task_id as string)}
          >
            Imported · view task
          </button>
        ) : (
          <button
            type="button"
            className="tk-btn"
            disabled={!canImport || importing}
            onClick={() => onImport(item)}
          >
            {importing ? <Loader2 size={13} className="spin" /> : null}
            Import as task
          </button>
        )}
      </div>
    </li>
  );
}

export function GitHubView({
  token,
  workspaceId,
  projectId,
  onOpenSettings,
  onOpenTask,
}: {
  token: string;
  workspaceId: string | null;
  projectId: string | null;
  onOpenSettings: () => void;
  onOpenTask: (taskId: string) => void;
}) {
  const [repos, setRepos] = useState<GitHubRepo[] | null>(null);
  const [repoSearch, setRepoSearch] = useState("");
  const [repo, setRepo] = useState("");
  const [kind, setKind] = useState<Kind>("all");
  const [state, setState] = useState<State>("open");
  const [items, setItems] = useState<GitHubItem[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [notLinked, setNotLinked] = useState(false);
  const [error, setError] = useState("");
  const [busyNumber, setBusyNumber] = useState<number | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [linking, setLinking] = useState(false);
  const [toast, setToast] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(""), 3500);
    return () => window.clearTimeout(t);
  }, [toast]);

  const fail = (err: unknown) => {
    const s = errorState(err);
    setNotLinked(s.notLinked);
    setError(s.message);
  };

  useEffect(() => {
    if (!workspaceId) return;
    let cancelled = false;
    setRepos(null);
    setNotLinked(false);
    setError("");
    api<GitHubRepo[]>(`/workspaces/${workspaceId}/github/repos`, token)
      .then((list) => {
        if (cancelled) return;
        setRepos(list);
        setRepo((current) =>
          list.some((r) => r.full_name === current) ? current : list[0]?.full_name ?? "",
        );
      })
      .catch((err) => {
        if (!cancelled) {
          setRepos([]);
          fail(err);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, workspaceId, reload]);

  const itemsPath = useCallback(
    (page: number) =>
      `/workspaces/${workspaceId}/github/items?repo=${encodeURIComponent(repo)}&kind=${kind}&state=${state}&page=${page}`,
    [workspaceId, repo, kind, state],
  );

  useEffect(() => {
    if (!workspaceId || !repo) {
      setItems([]);
      setNextPage(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    api<GitHubItemsPage>(itemsPath(1), token)
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setNextPage(page.next_page);
      })
      .catch((err) => {
        if (!cancelled) {
          setItems([]);
          setNextPage(null);
          fail(err);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, workspaceId, repo, kind, state, itemsPath, reload]);

  const loadMore = async () => {
    if (!nextPage) return;
    setLoadingMore(true);
    try {
      const page = await api<GitHubItemsPage>(itemsPath(nextPage), token);
      setItems((current) => {
        const seen = new Set(current.map((i) => i.number + ":" + i.is_pr));
        return [...current, ...page.items.filter((i) => !seen.has(i.number + ":" + i.is_pr))];
      });
      setNextPage(page.next_page);
    } catch (err) {
      fail(err);
    } finally {
      setLoadingMore(false);
    }
  };

  const refreshItems = async () => {
    const page = await api<GitHubItemsPage>(itemsPath(1), token);
    setItems(page.items);
    setNextPage(page.next_page);
  };

  const importItem = async (item: GitHubItem) => {
    if (!projectId) return;
    setBusyNumber(item.number);
    try {
      // `numbers` narrows the sync to this item when the backend supports it.
      const result = await api<GitHubSyncResult>("/github/sync", token, {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          repo,
          state: item.state === "open" ? "open" : "closed",
          include_issues: !item.is_pr,
          include_prs: item.is_pr,
          numbers: [item.number],
        }),
      });
      setToast(`Imported #${item.number} (${result.created} new, ${result.updated} updated)`);
      await refreshItems();
    } catch (err) {
      setToast(errorState(err).message || "Import failed");
    } finally {
      setBusyNumber(null);
    }
  };

  const importAll = async () => {
    if (!projectId || !repo) return;
    setSyncing(true);
    try {
      const result = await api<GitHubSyncResult>("/github/sync", token, {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          repo,
          state,
          include_issues: kind !== "pr",
          include_prs: kind !== "issue",
        }),
      });
      setToast(
        `Imported ${result.created} new, refreshed ${result.updated}` +
          (result.truncated ? ". Result was truncated; run again or narrow the filters." : ""),
      );
      await refreshItems();
    } catch (err) {
      setToast(errorState(err).message || "Import failed");
    } finally {
      setSyncing(false);
    }
  };

  const linkRepo = async () => {
    if (!projectId || !repo) return;
    setLinking(true);
    try {
      await api("/github/links", token, {
        method: "POST",
        body: JSON.stringify({ project_id: projectId, repo }),
      });
      setToast("Repo linked to this project for live sync");
      setReload((n) => n + 1);
    } catch (err) {
      setToast(errorState(err).message || "Could not link repo");
    } finally {
      setLinking(false);
    }
  };

  const filteredRepos = useMemo(() => {
    const q = repoSearch.trim().toLowerCase();
    const list = (repos ?? []).filter((r) => !q || r.full_name.toLowerCase().includes(q));
    const current = (repos ?? []).find((r) => r.full_name === repo);
    return current && !list.includes(current) ? [current, ...list] : list;
  }, [repos, repoSearch, repo]);
  const current = repos?.find((r) => r.full_name === repo);

  if (!workspaceId) {
    return (
      <div className="tk-page gh-page">
        <div className="gh-empty">Select a workspace to browse GitHub.</div>
      </div>
    );
  }

  return (
    <div className="tk-page gh-page">
      <div className="tk-head">
        <div>
          <div className="tk-eyebrow">GITHUB</div>
          <h2>Issues and pull requests</h2>
        </div>
        {!notLinked && repos && repos.length > 0 && (
          <div className="tk-head-actions">
            <Button
              className="button"
              disabled={!projectId || !repo || current?.linked}
              title={!projectId ? "Select a project first" : undefined}
              onClick={linkRepo}
            >
              <Github size={15} />
              {current?.linked ? "Linked for live sync" : linking ? "Linking…" : "Link repo to this project"}
            </Button>
            <Button
              className="button primary"
              disabled={!projectId || !repo || syncing}
              title={!projectId ? "Select a project first" : undefined}
              onClick={importAll}
            >
              {syncing ? <Loader2 size={15} className="spin" /> : null} Import all
            </Button>
          </div>
        )}
      </div>

      {notLinked ? (
        <div className="gh-empty">
          <Github size={28} />
          <h3>Affinebot is not linked to this workspace</h3>
          <p>Link Affinebot to browse repositories its GitHub App can access.</p>
          <Button className="button primary" onClick={onOpenSettings}>
            Open Settings &gt; Integrations
          </Button>
        </div>
      ) : repos === null ? (
        <div className="gh-empty">
          <Loader2 size={20} className="spin" /> Loading repositories…
        </div>
      ) : error && repos.length === 0 ? (
        <div className="gh-empty gh-error" role="alert">
          <AlertTriangle size={24} />
          <p>{error}</p>
          <button type="button" className="tk-btn" onClick={() => setReload((n) => n + 1)}>
            <RefreshCw size={13} /> Retry
          </button>
        </div>
      ) : repos.length === 0 ? (
        <div className="gh-empty">
          <p>No repositories are visible to the Affinebot GitHub App for this workspace.</p>
        </div>
      ) : (
        <>
          {!projectId && (
            <p className="tk-hint">
              Select a project in the sidebar to import items as tasks.
            </p>
          )}
          <div className="gh-toolbar">
            <label className="tk-search">
              <Search size={15} />
              <input
                placeholder="Filter repositories…"
                value={repoSearch}
                onChange={(e) => setRepoSearch(e.target.value)}
                aria-label="Filter repositories"
              />
            </label>
            <select
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              aria-label="Repository"
              className="gh-select"
            >
              {filteredRepos.map((r) => (
                <option key={r.full_name} value={r.full_name}>
                  {r.full_name}
                  {r.private ? " (private)" : ""}
                  {r.linked ? " · linked" : ""}
                </option>
              ))}
            </select>
            <div className="gh-tabs" role="tablist" aria-label="Kind">
              {(["all", "issue", "pr"] as Kind[]).map((k) => (
                <button
                  key={k}
                  type="button"
                  role="tab"
                  aria-selected={kind === k}
                  className={kind === k ? "active" : ""}
                  onClick={() => setKind(k)}
                >
                  {k === "all" ? "All" : k === "issue" ? "Issues" : "Pull requests"}
                </button>
              ))}
            </div>
            <select
              value={state}
              onChange={(e) => setState(e.target.value as State)}
              aria-label="State"
              className="gh-select"
            >
              <option value="open">Open</option>
              <option value="closed">Closed</option>
              <option value="all">All states</option>
            </select>
          </div>
          {current && (
            <div className="gh-repo-meta">
              {current.private && (
                <span className="tk-chip">
                  <Lock size={10} /> Private
                </span>
              )}
              {current.linked && <span className="tk-chip">Linked</span>}
              <span>default branch {current.default_branch}</span>
            </div>
          )}
          {error && (
            <div className="gh-inline-error" role="alert">
              {error}
            </div>
          )}
          {loading ? (
            <div className="gh-empty">
              <Loader2 size={20} className="spin" /> Loading…
            </div>
          ) : items.length === 0 ? (
            <div className="gh-empty">Nothing matches these filters.</div>
          ) : (
            <ul className="gh-list">
              {items.map((item) => (
                <GitHubItemRow
                  key={(item.is_pr ? "pr-" : "i-") + item.number}
                  item={item}
                  canImport={!!projectId}
                  importing={busyNumber === item.number}
                  onImport={importItem}
                  onOpenTask={onOpenTask}
                />
              ))}
            </ul>
          )}
          {nextPage && !loading && (
            <div className="gh-more">
              <button type="button" className="tk-btn" disabled={loadingMore} onClick={loadMore}>
                {loadingMore ? <Loader2 size={13} className="spin" /> : null} Load more
              </button>
            </div>
          )}
        </>
      )}
      {toast && <div className="tk-toast">{toast}</div>}
    </div>
  );
}
