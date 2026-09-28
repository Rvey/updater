import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  CircleHelp,
  Code2,
  Command,
  Copy,
  FileCode2,
  GitBranch,
  GitCommitHorizontal,
  Github,
  Inbox,
  LockKeyhole,
  KeyRound,
  LogOut,
  Menu,
  MessageCircle,
  Moon,
  Plus,
  Search,
  Settings2,
  Sparkles,
  StickyNote,
  Sun,
  X,
} from "lucide-react";
import type { ImpactNote, NewUpdate, Question, Update } from "./types";
import { NotesView } from "./notes";
import { TechDebtView } from "./techdebt";
import { Button } from "./components/ui/button";
import Homepage from "./marketing/Homepage";

const apiBase = import.meta.env.VITE_API_BASE_URL || "";

async function request<T>(
  path: string,
  token: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`${apiBase}/api${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(
      body.detail || `Request failed (${response.status})`,
    ) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return response.json() as Promise<T>;
}

function repoName(url: string) {
  try {
    const path = new URL(url).pathname.replace(/\.git$/, "").replace(/\/$/, "");
    return path.split("/").filter(Boolean).slice(-1)[0] || url;
  } catch {
    return url;
  }
}

function repoOwner(url: string) {
  try {
    return (
      new URL(url).pathname.split("/").filter(Boolean).slice(-2, -1)[0] || ""
    );
  } catch {
    return "";
  }
}

function dateLabel(date: string) {
  return new Date(date).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function relativeDate(date: string) {
  const days = Math.floor((Date.now() - new Date(date).getTime()) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return dateLabel(date);
}

function initials(name: string) {
  return name.slice(0, 2).toUpperCase();
}

const UPDATES_PAGE_SIZE = 8;

function fullDateTime(date: string) {
  try {
    return new Date(date).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return date;
  }
}

async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    try {
      const field = document.createElement("textarea");
      field.value = value;
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      const ok = document.execCommand("copy");
      field.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  if (!value) return null;
  return (
    <button
      className="copy-chip"
      aria-label={"Copy " + label}
      title={"Copy " + label}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        copyText(value).then((ok) => {
          if (ok) {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1400);
          }
        });
      }}
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function Logo() {
  return (
    <div className="brand">
      <span className="brand-mark">
        <span />
      </span>
      <span>
        updater<span className="brand-period">.</span>
      </span>
    </div>
  );
}

function EmptyState({
  onSetup,
  onNew,
}: {
  onSetup: () => void;
  onNew: () => void;
}) {
  return (
    <div className="empty-state">
      <div className="empty-illustration">
        <span className="empty-paper p1" />
        <span className="empty-paper p2" />
        <span className="empty-paper p3" />
        <span className="empty-star">✳</span>
      </div>
      <div className="eyebrow">YOUR SHIP LOG STARTS HERE</div>
      <h2>
        Every feature has a story.
        <br />
        Keep yours close.
      </h2>
      <p>
        Connect your coding agent and shipped work will appear here with the
        why, the how, and what changed.
      </p>
      <div className="empty-actions">
        <Button className="button primary" onClick={onSetup}>
          Connect an agent <ArrowRight size={16} />
        </Button>
        <button className="button subtle" onClick={onNew}>
          Add manually
        </button>
      </div>
    </div>
  );
}

function InfoSection({
  number,
  title,
  children,
}: {
  number: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="info-section">
      <div className="section-index">{number}</div>
      <div>
        <h3>{title}</h3>
        <div className="section-body">{children}</div>
      </div>
    </section>
  );
}

function shellQuote(value: string) {
  return "'" + value.replace(/'/g, "'\''") + "'";
}

function SetupModal({ close, serverToken }: { close: () => void; serverToken: string }) {
  const tokenConfigured = Boolean(serverToken);
  const [copied, setCopied] = useState(false);
  const [copiedOne, setCopiedOne] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const [tab, setTab] = useState<"opencode" | "codex" | "claude">("opencode");
  const [secured, setSecured] = useState(tokenConfigured);
  const [embedToken, setEmbedToken] = useState(tokenConfigured);
  const defaultOrigin = apiBase || (window.location.port === "5173"
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : window.location.origin);
  const [mcpUrl, setMcpUrl] = useState(new URL("/mcp", defaultOrigin).href);
  const useEmbedded = secured && embedToken && serverToken.length > 0;
  const commands = {
    opencode: `opencode mcp add updater --global --url ${mcpUrl}${secured ? (useEmbedded ? ` --header ${shellQuote("Authorization=Bearer " + serverToken)}` : ' --header "Authorization=Bearer {env:UPDATER_TOKEN}"') : ""}`,
    codex: `codex mcp add updater --url ${mcpUrl}${secured ? (useEmbedded ? ` --bearer-token ${shellQuote(serverToken)}` : " --bearer-token-env-var UPDATER_TOKEN") : ""}`,
    claude: `claude mcp add --transport http --scope user updater ${mcpUrl}${secured ? (useEmbedded ? ` --header ${shellQuote("Authorization: Bearer " + serverToken)}` : ' --header "Authorization: Bearer $UPDATER_TOKEN"') : ""}`,
  };
  const verify = {
    opencode: "opencode mcp list",
    codex: "codex mcp list",
    claude: "claude mcp list",
  };
  const connectUrl = new URL('/connect.sh', defaultOrigin).href;
  const oneStep = {
    opencode: 'curl -fsSL ' + connectUrl + ' | bash -s -- --url ' + mcpUrl + ' --agents opencode' + (useEmbedded ? ' --token ' + shellQuote(serverToken) : ''),
    codex: 'curl -fsSL ' + connectUrl + ' | bash -s -- --url ' + mcpUrl + ' --agents codex' + (useEmbedded ? ' --token ' + shellQuote(serverToken) : ''),
    claude: 'curl -fsSL ' + connectUrl + ' | bash -s -- --url ' + mcpUrl + ' --agents claude' + (useEmbedded ? ' --token ' + shellQuote(serverToken) : ''),
  };
  const oneStepAll = 'curl -fsSL ' + connectUrl + ' | bash -s -- --url ' + mcpUrl + ' --agents all' + (useEmbedded ? ' --token ' + shellQuote(serverToken) : '');
  const copy = async () => {
    setCopyError(false);
    const field = document.createElement("textarea");
    field.value = commands[tab];
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const copiedWithSelection = document.execCommand("copy");
    field.remove();
    if (!copiedWithSelection) {
      try {
        await Promise.race([
          navigator.clipboard.writeText(commands[tab]),
          new Promise<never>((_, reject) => window.setTimeout(() => reject(new Error("Clipboard unavailable")), 1000)),
        ]);
      } catch {
        setCopyError(true);
        return;
      }
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };
  const copyOne = async () => {
    setCopyError(false);
    try {
      await navigator.clipboard.writeText(oneStep[tab]);
    } catch {
      setCopyError(true);
      return;
    }
    setCopiedOne(true);
    window.setTimeout(() => setCopiedOne(false), 1800);
  };
  return (
    <div className="modal-backdrop" onMouseDown={close}>
      <div
        className="modal setup-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Connect an agent"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <button
          className="icon-button modal-close"
          aria-label="Close"
          onClick={close}
        >
          <X size={18} />
        </button>
        <div className="modal-icon">
          <Command size={22} />
        </div>
        <h2>Connect your coding agent</h2>
        <p className="modal-intro">
          Run one command in your terminal. Your agent can then publish and read
          feature updates through Updater.
        </p>
        <label className="setup-field">
          MCP server URL
          <input type="url" value={mcpUrl} onChange={(event) => setMcpUrl(event.target.value)} spellCheck={false} />
        </label>
        <label className="setup-check">
          <input type="checkbox" checked={secured} onChange={(event) => setSecured(event.target.checked)} />
          My server requires an Updater token
        </label>
        {secured && serverToken && (
          <label className="setup-check">
            <input type="checkbox" checked={embedToken} onChange={(event) => setEmbedToken(event.target.checked)} />
            Insert my current token directly (copy-paste ready)
          </label>
        )}
        <div className="setup-tabs">
          {(["opencode", "codex", "claude"] as const).map((item) => (
            <button
              key={item}
              className={tab === item ? "active" : ""}
              onClick={() => setTab(item)}
            >
              {item === "codex"
                ? "Codex"
                : item === "claude"
                  ? "Claude Code"
                  : "OpenCode"}
            </button>
          ))}
        </div>
        <p className='setup-verify'>One-step (recommended): MCP + <code>/updater</code>, <code>/updater-ship</code>, <code>/updater-check</code>, <code>/updater-impact</code>, <code>/tech-depth</code></p>
        <div className='code-block'>
          <button aria-label='Copy one-step command' onClick={copyOne}>
            {copiedOne ? <Check size={15} /> : <Copy size={15} />}{' '}
            {copiedOne ? 'Copied' : 'Copy'}
          </button>
          <pre>{oneStep[tab]}</pre>
        </div>
        <p className='setup-verify'>All agents at once (copy manually): <code>{oneStepAll}</code></p>
        <p className='setup-verify'>Manual (MCP only):</p>
        <div className="code-block">
          <button aria-label="Copy command" onClick={copy}>
            {copied ? <Check size={15} /> : <Copy size={15} />}{" "}
            {copied ? "Copied" : "Copy"}
          </button>
          <pre>{commands[tab]}</pre>
        </div>
        {copyError && <p className="setup-token-note">Copy was blocked by the browser. Select the command above to copy it.</p>}
        <p className="setup-verify">Check connection: <code>{verify[tab]}</code></p>
        {useEmbedded ? (
          <p className="setup-token-note">
            This command contains your secret token. Anyone with it can access your workspace. It will also be saved in your shell history
            (and in Claude Code's MCP settings file). Untick the box above for the safer env-var version.
          </p>
        ) : (
          secured && (
            <p className="setup-token-note">
              Set <code>UPDATER_TOKEN</code> in the terminal before running the command and launching the agent. Claude Code saves the expanded
              authorization header in its user MCP settings.
            </p>
          )
        )}
        <div className="setup-tip">
          <Sparkles size={16} />
          <span>
            One-step also installs <code>/updater</code> (bare ships the last verified changes, with args it does check, impact, or list), plus <code>/updater-ship</code>, <code>/updater-check</code>, <code>/updater-impact</code> and <code>/tech-depth</code>, for opencode, codex, claude and Cursor. Run the installer bare for prompts (token, agents, scope).
          </span>
        </div>
      </div>
    </div>
  );
}

function NewModal({
  close,
  save,
  saving,
}: {
  close: () => void;
  save: (value: NewUpdate) => Promise<void>;
  saving: boolean;
}) {
  const [form, setForm] = useState({
    title: "",
    summary: "",
    repo_url: "",
    why: "",
    how_it_works: "",
    impact: "",
    tradeoffs: "",
    learning_notes: "",
    files_changed: "",
    tags: "",
  });
  const [error, setError] = useState("");
  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      await save({
        ...form,
        files_changed: form.files_changed
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
        tags: form.tags
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save update");
    }
  };
  const field = (
    name: keyof typeof form,
    label: string,
    placeholder: string,
    multiline = false,
    required = false,
  ) => (
    <label className="form-field">
      <span>{label}</span>
      {multiline ? (
        <textarea
          required={required}
          value={form[name]}
          placeholder={placeholder}
          onChange={(e) => setForm({ ...form, [name]: e.target.value })}
        />
      ) : (
        <input
          required={required}
          value={form[name]}
          placeholder={placeholder}
          onChange={(e) => setForm({ ...form, [name]: e.target.value })}
        />
      )}
    </label>
  );
  return (
    <div className="modal-backdrop" onMouseDown={close}>
      <div
        className="modal new-modal"
        role="dialog"
        aria-modal="true"
        aria-label="New update"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <button
          className="icon-button modal-close"
          aria-label="Close"
          onClick={close}
        >
          <X size={18} />
        </button>
        <h2>Capture an update</h2>
        <p className="modal-intro">
          Keep the context you will want when you revisit this code.
        </p>
        <form onSubmit={onSubmit}>
          <div className="form-grid">
            {field(
              "title",
              "Feature title",
              "e.g. Faster project search",
              false,
              true,
            )}
            {field(
              "repo_url",
              "Repository URL",
              "https://github.com/you/project",
              false,
              true,
            )}
          </div>
          {field(
            "summary",
            "What shipped",
            "A short summary of the finished change",
            true,
            true,
          )}
          {field(
            "why",
            "Why it was built",
            "The problem, request, or decision behind it",
            true,
            true,
          )}
          {field(
            "how_it_works",
            "How it works",
            "Walk through the important code path",
            true,
            true,
          )}
          {field(
            "impact",
            "Expected impact",
            "Who or what changes as a result",
            true,
            true,
          )}
          <div className="form-grid">
            {field("files_changed", "Files changed", "One path per line", true)}
            {field("tags", "Tags", "search, performance, ui")}
          </div>
          {field(
            "tradeoffs",
            "Tradeoffs",
            "Known limits and follow-up work",
            true,
          )}
          {field(
            "learning_notes",
            "Learning notes",
            "What is worth remembering?",
            true,
          )}
          {error && <div className="form-error">{error}</div>}
          <div className="modal-footer">
            <button type="button" className="button subtle" onClick={close}>
              Cancel
            </button>
            <Button type="submit" className="button primary" disabled={saving}>
              {saving ? "Saving…" : "Save update"} <ArrowRight size={16} />
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
function UpdateDetail({
  update,
  token,
  onQuestion,
  onImpact,
  onRefresh,
  onBack,
}: {
  update: Update;
  token: string;
  onQuestion: (question: Question) => void;
  onImpact: (note: ImpactNote) => void;
  onRefresh: (item: Update) => void;
  onBack: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  const [impactDraft, setImpactDraft] = useState("");
  const [requestingContext, setRequestingContext] = useState(false);
  const [contextError, setContextError] = useState("");
  const [contextSent, setContextSent] = useState(false);
  const [threadOpen, setThreadOpen] = useState(false);
  const [composerOpen, setComposerOpen] = useState(true);
 useEffect(() => {
   setThreadOpen(false);
   setComposerOpen(true);
   setQuestion("");
   setError("");
   setContextSent(false);
   setContextError("");
 }, [update.id]);
 const pendingRequests = (update.context_requests ?? []).filter((item) => item.status === "pending");
  const fulfilledRequests = (update.context_requests ?? []).filter((item) => item.status === "fulfilled");
  useEffect(() => {
    if (pendingRequests.length === 0) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const refreshed = await request<Update>(`/updates/${update.id}`, token);
        if (!cancelled) onRefresh(refreshed);
      } catch {
        // Keep showing the pending state; a failed poll is not a request error.
      }
    };
    const timer = window.setInterval(poll, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [update.id, pendingRequests.length, token]);
  const askAgent = async () => {
    if (requestingContext) return;
    setRequestingContext(true);
    setContextError("");
    try {
      const prompt = question.trim() || "Send the key code excerpts for this change.";
      await request(`/updates/${update.id}/context-requests`, token, {
        method: "POST",
        body: JSON.stringify({ question: prompt }),
      });
      const refreshed = await request<Update>(`/updates/${update.id}`, token);
      onRefresh(refreshed);
      setContextSent(true);
    } catch (err) {
      setContextError(err instanceof Error ? err.message : "Unable to request context");
    } finally {
      setRequestingContext(false);
    }
  };
  const [savingImpact, setSavingImpact] = useState(false);
  const [impactError, setImpactError] = useState("");
  const ask = async (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim() || asking) return;
    setAsking(true);
    setError("");
    try {
      const answer = await request<Question>(
        `/updates/${update.id}/questions`,
        token,
      { method: "POST", body: JSON.stringify({ question: question.trim() }) },
      );
      onQuestion(answer);
      setQuestion("");
      setThreadOpen(true);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to answer question",
      );
    } finally {
      setAsking(false);
    }
  };
  const saveImpact = async (event: FormEvent) => {
    event.preventDefault();
    if (!impactDraft.trim() || savingImpact) return;
    setSavingImpact(true);
    setImpactError("");
    try {
      const note = await request<ImpactNote>(
        `/updates/${update.id}/impact-notes`,
        token,
        { method: "POST", body: JSON.stringify({ note: impactDraft.trim() }) },
      );
      onImpact(note);
      setImpactDraft("");
    } catch (err) {
      setImpactError(
        err instanceof Error ? err.message : "Unable to save impact note",
      );
    } finally {
      setSavingImpact(false);
    }
  };
  return (
    <div className="detail-wrap" key={update.id}>
      <div className="detail-scroll">
        <div className="detail-content">
          <button className="mobile-back" onClick={onBack}>
            <ArrowLeft size={16} /> All updates
          </button>
      <div className="detail-topline">
        <span className="detail-kicker">
          <span className="live-dot" /> SHIPPED FEATURE
        </span>
        <span>{dateLabel(update.shipped_at)}</span>
      </div>
      <h1>{update.title}</h1>
      <p className="detail-summary">{update.summary}</p>
      {(update.tags?.length ?? 0) > 0 && (
        <div className="detail-tags">
          {update.tags.map((tag) => (
            <span className="tag" key={tag}>
              {tag}
            </span>
          ))}
        </div>
      )}
      <div className="detail-meta">
        <a href={update.repo_url} target="_blank" rel="noreferrer">
          <Github size={15} /> {repoOwner(update.repo_url)}/
          {repoName(update.repo_url)} <ArrowUpRight size={14} />
        </a>
        {update.pr_url && (
          <a href={update.pr_url} target="_blank" rel="noreferrer">
            View pull request <ArrowUpRight size={14} />
          </a>
        )}
        {update.commit_sha && (
          <span title={update.commit_sha}>
            <GitCommitHorizontal size={14} /> {update.commit_sha.slice(0, 7)}
            <CopyButton value={update.commit_sha} label="commit SHA" />
          </span>
        )}
        {update.branch && (
          <span>
            <GitBranch size={14} /> {update.branch}
          </span>
        )}
        {update.author_agent && (
          <span>
            <Sparkles size={14} /> {update.author_agent}
          </span>
        )}
      </div>
      <div className="record-grid" aria-label="Record details">
        <div className="record-field">
          <span>Update ID</span>
          <code title={update.id}>{update.id}</code>
          <CopyButton value={update.id} label="update ID" />
        </div>
        <div className="record-field">
          <span>External ID</span>
          {update.external_id ? (
            <>
              <code title={update.external_id}>{update.external_id}</code>
              <CopyButton value={update.external_id} label="external ID" />
            </>
          ) : (
            <em>—</em>
          )}
        </div>
        <div className="record-field">
          <span>Repository URL</span>
          <code title={update.repo_url}>{update.repo_url}</code>
          <CopyButton value={update.repo_url} label="repository URL" />
        </div>
        <div className="record-field">
          <span>Branch</span>
          {update.branch ? <code>{update.branch}</code> : <em>—</em>}
        </div>
        <div className="record-field">
          <span>Commit SHA</span>
          {update.commit_sha ? (
            <>
              <code title={update.commit_sha}>{update.commit_sha}</code>
              <CopyButton value={update.commit_sha} label="commit SHA" />
            </>
          ) : (
            <em>—</em>
          )}
        </div>
        <div className="record-field">
          <span>Pull request</span>
          {update.pr_url ? (
            <a href={update.pr_url} target="_blank" rel="noreferrer">
              {update.pr_url} <ArrowUpRight size={12} />
            </a>
          ) : (
            <em>—</em>
          )}
        </div>
        <div className="record-field">
          <span>Author agent</span>
          {update.author_agent ? <code>{update.author_agent}</code> : <em>—</em>}
        </div>
        {(update as { user_id?: string | null }).user_id ? (
          <div className="record-field">
            <span>User ID</span>
            <code>{(update as { user_id?: string | null }).user_id}</code>
          </div>
        ) : null}
        <div className="record-field">
          <span>Shipped at</span>
          <code title={update.shipped_at}>
            {fullDateTime(update.shipped_at)} · {relativeDate(update.shipped_at)}
          </code>
        </div>
        <div className="record-field">
          <span>Created at</span>
          <code title={update.created_at}>
            {fullDateTime(update.created_at)} · {relativeDate(update.created_at)}
          </code>
        </div>
        <div className="record-field">
          <span>Counts</span>
          <code>
            {(update.files_changed?.length ?? 0)} files · {(update.tags?.length ?? 0)} tags ·{" "}
            {(update.code_context?.length ?? 0)} excerpts · {update.questions.length} questions ·{" "}
            {update.impact_notes.length} impact notes · {(update.context_requests?.length ?? 0)} context requests
          </code>
        </div>
      </div>
      <div className="detail-divider" />
      <InfoSection number="01" title="Why this was built">
        <p>{update.why}</p>
      </InfoSection>
      <InfoSection number="02" title="How it works">
        <p>{update.how_it_works}</p>
        {update.learning_notes && (
          <div className="learning-note">
            <BookOpen size={17} />
            <div>
              <strong>The part to remember</strong>
              <p>{update.learning_notes}</p>
            </div>
          </div>
        )}
      </InfoSection>
      <InfoSection number="03" title="What it changes">
        <p>{update.impact}</p>
      </InfoSection>
      <InfoSection number="04" title="Impact over time">
        <div className="impact-timeline">
          {update.impact_notes.length ? (
            update.impact_notes.map((note) => (
              <div className="impact-entry" key={note.id}>
                <span>{dateLabel(note.created_at)}</span>
                <p>{note.note}</p>
              </div>
            ))
          ) : (
            <p className="impact-empty">
              {Math.floor(
                (Date.now() - new Date(update.shipped_at).getTime()) / 86400000,
              ) < 2
                ? "Too early for outcomes — this was just shipped. Add the first observation once you've seen it live."
                : "Shipped " + relativeDate(update.shipped_at) + " with no observations yet. Add what actually changed — metrics, feedback, bugs, or follow-ups. Your connected agent can also record these via add_feature_impact."}
            </p>
          )}
        </div>
        <form className="impact-form" onSubmit={saveImpact}>
          <input
            aria-label="Record observed impact"
            placeholder="Record an outcome or observation…"
            value={impactDraft}
            onChange={(e) => setImpactDraft(e.target.value)}
          />
          <button
            aria-label="Save impact note"
            disabled={savingImpact || impactDraft.trim().length < 3}
          >
            <Plus size={15} />
          </button>
        </form>
        {impactError && <div className="form-error">{impactError}</div>}
      </InfoSection>
      <InfoSection number="05" title="Tradeoffs & follow-ups">
        {update.tradeoffs ? <p>{update.tradeoffs}</p> : <p className="impact-empty">No tradeoffs recorded.</p>}
      </InfoSection>
      <InfoSection number="06" title="Learning notes">
        {update.learning_notes ? (
          <p>{update.learning_notes}</p>
        ) : (
          <p className="impact-empty">No learning notes recorded.</p>
        )}
      </InfoSection>
      <section className="files-section">
        <div className="files-title">
          <FileCode2 size={16} /> ALL FILES CHANGED <span>{update.files_changed.length}</span>
        </div>
        {update.files_changed.length > 0 ? (
          <div className="file-list">
            {update.files_changed.map((file) => (
              <div key={file}>
                <Code2 size={14} />
                <span>{file}</span>
                <CopyButton value={file} label="file path" />
              </div>
            ))}
          </div>
        ) : (
          <p className="impact-empty">No files recorded.</p>
        )}
      </section>
      <section className="files-section">
        <div className="files-title">
          <Code2 size={16} /> ALL CODE EXCERPTS <span>{update.code_context?.length ?? 0}</span>
        </div>
        {(update.code_context?.length ?? 0) > 0 ? (
          update.code_context.map((excerpt, index) => (
            <div key={(excerpt.path ?? "excerpt") + "-" + index} className="code-excerpt">
              <div className="code-excerpt-path">
                <span>
                  {excerpt.path}
                  {excerpt.start_line != null && excerpt.end_line != null
                    ? " · lines " + excerpt.start_line + "-" + excerpt.end_line
                    : excerpt.start_line != null
                      ? " · from line " + excerpt.start_line
                      : ""}
                </span>
                <CopyButton value={excerpt.content} label="code excerpt" />
              </div>
              <pre className="code-excerpt-body">{excerpt.content}</pre>
            </div>
          ))
        ) : (
          <p className="impact-empty">No code excerpts attached yet. Ask your agent for code context below.</p>
        )}
      </section>
      <section className="files-section">
        <div className="files-title">
          <MessageCircle size={16} /> ALL CONTEXT REQUESTS{" "}
          <span>{update.context_requests?.length ?? 0}</span>
        </div>
        {(update.context_requests?.length ?? 0) > 0 ? (
          <div className="context-list">
            {update.context_requests.map((req) => (
              <div key={req.id} className="context-entry">
                <div className="context-entry-head">
                  <span className={"status-pill status-" + req.status}>{req.status}</span>
                  <span className="context-date" title={req.created_at}>
                    asked {fullDateTime(req.created_at)}
                  </span>
                  {req.fulfilled_at && (
                    <span className="context-date" title={req.fulfilled_at}>
                      {" · fulfilled "}{fullDateTime(req.fulfilled_at)}
                    </span>
                  )}
                </div>
                <p className="context-question">{req.question}</p>
                {(req.excerpts?.length ?? 0) > 0 && (
                  <div className="context-excerpts">
                    {req.excerpts.map((ex2, idx2) => (
                      <div key={(ex2.path ?? "excerpt") + "-" + idx2} className="code-excerpt">
                        <div className="code-excerpt-path">
                          <span>
                            {ex2.path}
                            {ex2.start_line != null && ex2.end_line != null
                              ? " · lines " + ex2.start_line + "-" + ex2.end_line
                              : ""}
                          </span>
                          <CopyButton value={ex2.content} label="code excerpt" />
                        </div>
                        <pre className="code-excerpt-body">{ex2.content}</pre>
                      </div>
                    ))}
                  </div>
                )}
                <div className="context-id">
                  <code title={req.id}>{req.id}</code>
                  <CopyButton value={req.id} label="request ID" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="impact-empty">No context requests yet.</p>
        )}
      </section>
      {(update.questions?.length ?? 0) > 0 && (
        <section className="files-section">
          <div className="files-title">
            <MessageCircle size={16} /> ALL QUESTIONS & ANSWERS <span>{update.questions.length}</span>
          </div>
          <div className="context-list">
            {update.questions.map((item) => (
              <div key={item.id} className="context-entry">
                <div className="context-entry-head">
                  <span className="status-pill">{item.source === "ai" ? "UPDATER AI" : "SAVED CONTEXT"}</span>
                  <span className="context-date" title={item.created_at}>
                    {fullDateTime(item.created_at)}
                  </span>
                </div>
                <p className="context-question">{item.question}</p>
                <p className="context-answer">{item.answer}</p>
              </div>
            ))}
          </div>
        </section>
      )}
      {false && update.files_changed.length > 0 && (
        <section className="files-section">
          <div className="files-title">
            <FileCode2 size={16} /> FILES TO EXPLORE{" "}
            <span>{update.files_changed.length}</span>
          </div>
          <div className="file-list">
            {update.files_changed.map((file) => (
              <div key={file}>
                <Code2 size={14} />
                <span>{file}</span>
              </div>
            ))}
          </div>
        </section>
      )}
      {false && (update.code_context?.length ?? 0) > 0 && (
        <section className="files-section">
          <div className="files-title">
            <Code2 size={16} /> CODE FROM YOUR AGENT{" "}
            <span>{update.code_context.length}</span>
          </div>
          {update.code_context.map((excerpt) => (
            <div key={(excerpt as { path?: string }).path} className="code-excerpt">
              <div className="code-excerpt-path">
                {excerpt.path}
                {excerpt.start_line && excerpt.end_line ? ` · lines ${excerpt.start_line}-${excerpt.end_line}` : ""}
              </div>
              <pre className="code-excerpt-body">{excerpt.content}</pre>
            </div>
          ))}
      </section>
      )}
      {(update.pr_url || update.commit_sha) && (
        <div className="source-links">
          {update.pr_url && (
            <a href={update.pr_url} target="_blank" rel="noreferrer">
              View pull request <ArrowUpRight size={14} />
            </a>
          )}
          {update.commit_sha && (
            <span title={update.commit_sha}>
              Commit {update.commit_sha.slice(0, 7)} · <code>{update.commit_sha}</code>{" "}
              <CopyButton value={update.commit_sha} label="commit SHA" />
            </span>
          )}
        </div>
      )}
        </div>
      </div>
      <div className={`detail-composer${composerOpen ? "" : " is-collapsed"}`}>
        {composerOpen && threadOpen && (
          <div className="thread-sheet">
            <div className="thread-sheet-scroll">
              {update.questions.length ? (
                update.questions.map((item) => (
                  <div className="question-pair" key={item.id}>
                    <div className="question-bubble">{item.question}</div>
                    <div className="answer-bubble">
                      <span className="answer-icon">
                        <Sparkles size={15} />
                      </span>
                      <div>
                        <div className="answer-label">
                          {item.source === "ai" ? "UPDATER AI" : "SAVED CONTEXT"}
                        </div>
                        <p>{item.answer}</p>
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <p className="thread-empty">
                  No questions yet. Ask the first one below — it will stay
                  attached to this update.
                </p>
              )}
            </div>
          </div>
        )}
        <div className="composer-bar">
          <div className="conversation-heading">
            <div>
              <MessageCircle size={18} />
              <h3>Ask about this update</h3>
            </div>
            <div className="composer-actions">
              {composerOpen && (
                <button
                  className="thread-toggle"
                  onClick={() => setThreadOpen((v) => !v)}
                  aria-expanded={threadOpen}
                  aria-label={threadOpen ? "Collapse thread" : "Expand thread"}
                >
                  <span>
                    {update.questions.length
                      ? `${update.questions.length} saved`
                      : "LEARN AS YOU GO"}
                  </span>
                  {threadOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </button>
              )}
              <button
                className="composer-collapse"
                onClick={() => setComposerOpen((v) => !v)}
                aria-expanded={composerOpen}
                aria-label={composerOpen ? "Collapse ask panel" : "Expand ask panel"}
                title={composerOpen ? "Collapse ask panel" : "Expand ask panel"}
              >
                {composerOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
              </button>
            </div>
          </div>
          {composerOpen && (
            <>
              <p className="composer-sub">
                Pick up the thread whenever you need to understand this feature again.
              </p>
              <form className="ask-form" onSubmit={ask}>
                <input
                  aria-label="Ask about this update"
                  placeholder="What would you like to understand?"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                />
                <button
                  aria-label="Send question"
                  disabled={asking || !question.trim()}
                >
                  <ArrowUpRight size={18} />
                </button>
              </form>
              {error && <div className="form-error">{error}</div>}
              <div className="ask-hint">
                <LockKeyhole size={12} /> Answers stay attached to this update
              </div>
              <div className="agent-proxy">
                <button className="button subtle" onClick={askAgent} disabled={requestingContext}>
                  {requestingContext ? "Asking your agent…" : "Ask my agent for code context"}
                </button>
                <p>
                  Saves a request to this update. Then, in your agent running from this repo checkout, ask it to check Updater — it reads the local files and sends back only the needed excerpts. This page auto-refreshes every 5s while a request is pending.
                </p>
                {contextSent && pendingRequests.length === 0 && fulfilledRequests.length === 0 && (
                  <p className="proxy-note">Request sent — in your agent run /updater-check or call list_context_requests, then fulfill it. New excerpts appear under Code from your agent.</p>
                )}
                {pendingRequests.length > 0 && (
                  <div className="proxy-pending">
                    <span>{pendingRequests.length} waiting on your agent</span>
                    {pendingRequests.map((item) => (
                      <p key={item.id}>“{item.question}”</p>
                    ))}
                    <p className="proxy-note">In your agent checkout run: /updater-check — or MCP list_context_requests then fulfill_context_request. Keep this page open; it will refresh automatically.</p>
                  </div>
                )}
                {fulfilledRequests.length > 0 && pendingRequests.length === 0 && (
                  <p className="proxy-note">Agent replied — see Code from your agent above, then ask again for a code-grounded answer.</p>
                )}
                {contextError && <div className="form-error">{contextError}</div>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

type ApiKeyInfo = {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

function KeysModal({ close, token }: { close: () => void; token: string }) {
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [name, setName] = useState("agent key");
  const [created, setCreated] = useState<{ name: string; key: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copiedKey, setCopiedKey] = useState(false);
  const [copyError, setCopyError] = useState(false);

  useEffect(() => {
    request<ApiKeyInfo[]>("/auth/keys", token)
      .then(setKeys)
      .catch((err) => setError(err.message));
  }, [token]);

  const create = (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setCopyError(false);
    setCopiedKey(false);
    request<{ id: string; name: string; prefix: string; key: string }>("/auth/keys", token, {
      method: "POST",
      body: JSON.stringify({ name }),
    })
      .then((item) => {
        setCreated({ name: item.name, key: item.key });
        return request<ApiKeyInfo[]>("/auth/keys", token);
      })
      .then(setKeys)
      .catch((err) => setError(err.message))
      .finally(() => setBusy(false));
  };

  const copyCreated = async () => {
    if (!created) return;
    setCopyError(false);
    try {
      await navigator.clipboard.writeText(created.key);
    } catch {
      try {
        const field = document.createElement("textarea");
        field.value = created.key;
        field.style.position = "fixed";
        field.style.opacity = "0";
        document.body.appendChild(field);
        field.select();
        const ok = document.execCommand("copy");
        field.remove();
        if (!ok) throw new Error("copy failed");
      } catch {
        setCopyError(true);
        return;
      }
    }
    setCopiedKey(true);
    window.setTimeout(() => setCopiedKey(false), 1800);
  };

  const revoke = (id: string) => {
    request<{ ok: boolean }>(`/auth/keys/${id}`, token, { method: "DELETE" })
      .then(() =>
        setKeys((current) =>
          current.map((item) =>
            item.id === id ? { ...item, revoked_at: new Date().toISOString() } : item,
          ),
        ),
      )
      .catch((err) => setError(err.message));
  };

  return (
    <div className="modal-backdrop" onMouseDown={close}>
      <div
        className="modal setup-modal"
        role="dialog"
        aria-modal="true"
        aria-label="API keys"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <button
          className="icon-button modal-close"
          aria-label="Close"
          onClick={close}
        >
          <X size={18} />
        </button>
        <div className="modal-icon">
          <KeyRound size={22} />
        </div>
        <h2>API keys</h2>
        <p className="modal-intro">
          Keys sign in your coding agents over MCP and HTTP. Treat a key like a password: keep it in an env var, never in git.
        </p>
        {created && (
          <div className="code-block">
            <button aria-label="Copy API key" onClick={copyCreated}>
              {copiedKey ? <Check size={15} /> : <Copy size={15} />}{" "}
              {copiedKey ? "Copied" : "Copy"}
            </button>
            <pre>{created.key}</pre>
          </div>
        )}
        {created && (
          <p className="setup-token-note">
            Copy it now in a safe place. This is the only time the full key is shown.
          </p>
        )}
        {created && copyError && (
          <p className="setup-token-note">Copy was blocked by the browser. Select the key above to copy it.</p>
        )}
        <form onSubmit={create}>
          <label className="setup-field">
            New key name
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
          </label>
          <Button type="submit" className="button primary" disabled={busy}>
            {busy ? "Creating…" : "Create key"}
          </Button>
        </form>
        {keys.map((item) => (
          <div key={item.id} className="code-block">
            {item.revoked_at ? (
              <button aria-label="Key revoked" disabled>
                Revoked
              </button>
            ) : (
              <button aria-label="Revoke key" onClick={() => revoke(item.id)}>
                Revoke
              </button>
            )}
            <pre>{item.name}  {item.prefix}…{item.last_used_at ? "  last used " + item.last_used_at.slice(0, 10) : "  never used"}{item.revoked_at ? "  REVOKED" : ""}</pre>
          </div>
        ))}
        {!keys.length && !error && <p className="setup-token-note">No keys yet.</p>}
        {error && <div className="form-error">{error}</div>}
      </div>
    </div>
  );
}


function WorkspaceApp() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem("updater-token") || "",
  );
  const [draftToken, setDraftToken] = useState(
    () => sessionStorage.getItem("updater-token") || "",
  );
  const [authMode, setAuthMode] = useState<"login" | "register" | "token">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [accountEmail, setAccountEmail] = useState<string | null>(null);
  const [keysOpen, setKeysOpen] = useState(false);
  const [updates, setUpdates] = useState<Update[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [updatesPage, setUpdatesPage] = useState(1);
  const [repo, setRepo] = useState("All updates");
  const [view, setView] = useState<"updates" | "questions" | "notes" | "tech-debt">("updates");
  const [loading, setLoading] = useState(true);
  const [unauthorized, setUnauthorized] = useState(false);
  const [error, setError] = useState("");
  const [setupOpen, setSetupOpen] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [mobileDetail, setMobileDetail] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    try {
      const saved = localStorage.getItem("updater-theme");
      if (saved === "light" || saved === "dark") return saved;
    } catch {
      /* ignore */
    }
    return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches
      ? "dark"
      : "light";
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem("updater-theme", theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    request<Update[]>("/updates?limit=500&offset=0", token)
      .then((items) => {
        if (cancelled) return;
        setUpdates(items);
        setSelectedId((current) =>
          current && items.some((item) => item.id === current)
            ? current
            : items[0]?.id || null,
        );
        setUnauthorized(false);
        setError("");
      })
      .catch((err) => {
        if (cancelled) return;
        setUnauthorized(err.status === 401);
        setError(err.status === 401 ? "" : err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (!token) {
      setAccountEmail(null);
      return;
    }
    request<{ email: string | null; legacy: boolean }>("/auth/me", token)
      .then((info) => setAccountEmail(info.legacy ? null : info.email))
      .catch(() => setAccountEmail(null));
  }, [token]);

  const repositories = useMemo(
    () => [...new Set(updates.map((item) => item.repo_url))],
    [updates],
  );
  const filtered = useMemo(
    () =>
      updates.filter((item) => {
        const matchesRepo = repo === "All updates" || item.repo_url === repo;
        const text =
          `${item.title} ${item.summary} ${item.why} ${item.how_it_works} ${item.tags.join(" ")}`.toLowerCase();
        const matchesSearch = text.includes(search.toLowerCase().trim());
        const matchesView = view === "updates" || item.questions.length > 0;
        return matchesRepo && matchesSearch && matchesView;
      }),
    [updates, repo, search, view],
  );
  const totalUpdatePages = Math.max(1, Math.ceil(filtered.length / UPDATES_PAGE_SIZE));
  const safeUpdatePage = Math.min(updatesPage, totalUpdatePages);
  const pagedFiltered = filtered.slice(
    (safeUpdatePage - 1) * UPDATES_PAGE_SIZE,
    safeUpdatePage * UPDATES_PAGE_SIZE,
  );
  const pageStart = filtered.length === 0 ? 0 : (safeUpdatePage - 1) * UPDATES_PAGE_SIZE + 1;
  const pageEnd = Math.min(safeUpdatePage * UPDATES_PAGE_SIZE, filtered.length);
  useEffect(() => {
    setUpdatesPage(1);
  }, [search, repo, view, updates.length]);
  const selected =
    filtered.find((item) => item.id === selectedId) || filtered[0];
  const questionCount = updates.reduce(
    (total, item) => total + item.questions.length,
    0,
  );

  const addUpdate = async (value: NewUpdate) => {
    setSaving(true);
    try {
      const item = await request<Update>("/updates", token, {
        method: "POST",
        body: JSON.stringify(value),
      });
      setUpdates((current) => [item, ...current]);
      setSelectedId(item.id);
      setRepo("All updates");
      setView("updates");
      setSearch("");
      setUpdatesPage(1);
      setNewOpen(false);
      setMobileDetail(true);
    } finally {
      setSaving(false);
    }
  };
  const addQuestion = (question: Question) =>
    setUpdates((current) =>
      current.map((item) =>
        item.id === selected?.id
          ? { ...item, questions: [...item.questions, question] }
          : item,
      ),
    );
  const addImpact = (note: ImpactNote) =>
    setUpdates((current) =>
      current.map((item) =>
        item.id === selected?.id
          ? { ...item, impact_notes: [...item.impact_notes, note] }
          : item,
      ),
    );
  const refreshUpdate = (item: Update) =>
    setUpdates((current) => current.map((existing) => (existing.id === item.id ? item : existing)));
  const chooseRepo = (value: string) => {
    setRepo(value);
    setView("updates");
    setMobileNav(false);
    setMobileDetail(false);
  };


  const openWithToken = (value: string) => {
    request<Update[]>("/updates?limit=500&offset=0", value)
      .then((items) => {
        sessionStorage.setItem("updater-token", value);
        setUpdates(items);
        setSelectedId(items[0]?.id || null);
        setToken(value);
        setUnauthorized(false);
        setError("");
      })
      .catch(() => setError("That token did not work."));
  };

  const submitAccount = (mode: "login" | "register") => {
    request<{ email: string; session_token: string }>(`/auth/${mode}`, "", {
      method: "POST",
      body: JSON.stringify({ email: authEmail, password: authPassword }),
    })
      .then((res) => {
        setAccountEmail(res.email);
        openWithToken(res.session_token);
      })
      .catch((err) => setError(err.message));
  };

  const signOut = () => {
    const current = token;
    sessionStorage.removeItem("updater-token");
    setToken("");
    setDraftToken("");
    setAccountEmail(null);
    setUpdates([]);
    setUnauthorized(true);
    if (current) {
      request<{ ok: boolean }>("/auth/logout", current, { method: "POST" }).catch(() => {});
    }
  };
  if (unauthorized)
    return (
      <div className="auth-screen">
        <div className="auth-panel">
          <div className="auth-top">
            <Logo />
            <button
              className="icon-button theme-toggle"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </button>
          </div>
          <div className="auth-symbol">
            <LockKeyhole size={25} />
          </div>
          <div className="eyebrow auth-eyebrow">{authMode === "register" ? "CREATE YOUR ACCOUNT" : authMode === "token" ? "AGENT ACCESS" : "WELCOME BACK"}</div>
          <h1>
            Your shipping memory,
            <br />
            kept private.
          </h1>
          <div className="setup-tabs">
            {(["login", "register", "token"] as const).map((item) => (
              <button
                key={item}
                className={authMode === item ? "active" : ""}
                onClick={() => {
                  setAuthMode(item);
                  setError("");
                }}
              >
                {item === "login" ? "Sign in" : item === "register" ? "Create account" : "Use a token"}
              </button>
            ))}
          </div>
          <p>
            {authMode === "register"
              ? "Create the first account on this server. Afterwards you can issue API keys for your agents."
              : authMode === "token"
                ? "Paste the server token or a personal API key."
                : "Sign in to open your workspace."}
          </p>
          {authMode === "token" ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                openWithToken(draftToken);
              }}
            >
              <input
                type="password"
                placeholder="Updater token or API key"
                value={draftToken}
                onChange={(e) => setDraftToken(e.target.value)}
              />
              <Button type="submit" className="button primary auth-submit">
                Open workspace <ArrowRight size={16} />
              </Button>
            </form>
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                submitAccount(authMode);
              }}
            >
              <input
                type="email"
                placeholder="Email"
                value={authEmail}
                onChange={(e) => setAuthEmail(e.target.value)}
                autoComplete="email"
              />
              <input
                type="password"
                placeholder="Password (8+ characters)"
                value={authPassword}
                onChange={(e) => setAuthPassword(e.target.value)}
                autoComplete={authMode === "login" ? "current-password" : "new-password"}
              />
              <Button type="submit" className="button primary auth-submit">
                {authMode === "login" ? "Sign in" : "Create account"} <ArrowRight size={16} />
              </Button>
            </form>
          )}
          {error && <div className="form-error">{error}</div>}
        </div>
      </div>
    );

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? "mobile-open" : ""}`}>
        <div className="sidebar-top">
          <Logo />
          <button
            className="mobile-close icon-button"
            onClick={() => setMobileNav(false)}
            aria-label="Close navigation"
          >
            <X size={18} />
          </button>
        </div>
        <div className="workspace-label">
          WORKSPACE <ChevronDown size={13} />
        </div>
        <nav className="primary-nav" aria-label="Main navigation">
          <button
            className={
              view === "updates" && repo === "All updates" ? "active" : ""
            }
            onClick={() => {
              setView("updates");
              setRepo("All updates");
              setMobileNav(false);
              setMobileDetail(false);
            }}
          >
            <Activity size={17} /> All updates <span>{updates.length}</span>
          </button>
          <button
            className={view === "questions" ? "active" : ""}
            onClick={() => {
              setView("questions");
              setRepo("All updates");
              setMobileNav(false);
              setMobileDetail(false);
            }}
          >
            <MessageCircle size={17} /> Conversations{" "}
            <span>{questionCount}</span>
          </button>
          <button
            className={view === "notes" ? "active" : ""}
            onClick={() => {
              setView("notes");
              setMobileNav(false);
              setMobileDetail(false);
            }}
          >
            <StickyNote size={17} /> Notes
          </button>
          <button
            className={view === "tech-debt" ? "active" : ""}
            onClick={() => {
              setView("tech-debt");
              setMobileNav(false);
              setMobileDetail(false);
            }}
          >
            <AlertTriangle size={17} /> Tech debt
          </button>
        </nav>
        <div className="sidebar-section-heading">
          <span>REPOSITORIES</span>
          <span>{repositories.length}</span>
        </div>
        <nav className="repo-nav" aria-label="Repositories">
          {repositories.map((url) => (
            <button
              key={url}
              className={repo === url ? "active" : ""}
              onClick={() => chooseRepo(url)}
            >
              <span className="repo-icon">{initials(repoName(url))}</span>
              <span>{repoName(url)}</span>
            </button>
          ))}
          {!repositories.length && (
            <p className="no-repos">Your repos will appear here.</p>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-rule" />
          <button
            onClick={() => {
              setSetupOpen(true);
              setMobileNav(false);
            }}
          >
            <Settings2 size={17} /> Connect an agent <ArrowUpRight size={15} />
          </button>
          <button
            onClick={() => {
              setKeysOpen(true);
              setMobileNav(false);
            }}
          >
            <KeyRound size={17} /> API keys
          </button>
          <button onClick={signOut}>
            <LogOut size={17} /> {accountEmail ? "Sign out (" + accountEmail + ")" : "Sign out"}
          </button>
          <div className="sidebar-foot">
            <span className="status-dot" /> YOUR WORK, REMEMBERED
          </div>
        </div>
      </aside>
      <main className={`workspace ${mobileDetail ? "show-mobile-detail" : ""}`}>
        <header className="topbar">
          <button
            className="mobile-menu icon-button"
            onClick={() => setMobileNav(true)}
            aria-label="Open navigation"
          >
            <Menu size={20} />
          </button>
          <div className="breadcrumbs">
            WORKSPACE <ChevronRight size={14} />{" "}
            <strong>
              {view === "notes"
                ? "Notes"
                : view === "tech-debt"
                  ? "Tech debt"
                  : view === "questions"
                    ? "Conversations"
                    : repo === "All updates"
                      ? "All updates"
                      : repoName(repo)}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="topbar-date">
              {new Date().toLocaleDateString("en-US", {
                weekday: "short",
                month: "short",
                day: "numeric",
              })}
            </span>
            <button
              className="icon-button theme-toggle"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </button>
            <div className="avatar">U</div>
          </div>
        </header>
        <div className="workspace-body">
          {view === "notes" ? (
            <NotesView token={token} repos={repositories} />
          ) : view === "tech-debt" ? (
            <TechDebtView token={token} repos={repositories} />
          ) : (
            <>
          <section className="feed-panel">
            <div className="feed-heading">
              <div>
                <div className="feed-eyebrow">
                  <span className="eyebrow-line" /> THE SHIP LOG
                </div>
                <h2>
                  {view === "questions"
                    ? "Conversations"
                    : repo === "All updates"
                      ? "All updates"
                      : repoName(repo)}
                </h2>
                <p>
                  {view === "questions"
                    ? "Questions and answers attached to your shipped work."
                    : "A clearer picture of everything you ship."}
                </p>
              </div>
              <button
                className="new-button"
                onClick={() => setNewOpen(true)}
                aria-label="Add update"
              >
                <Plus size={20} />
              </button>
            </div>
            <div className="feed-stats">
              <div>
                <strong>{String(updates.length).padStart(2, "0")}</strong>
                <span>FEATURES SHIPPED</span>
              </div>
              <div>
                <strong>{String(repositories.length).padStart(2, "0")}</strong>
                <span>REPOSITORIES</span>
              </div>
              <div>
                <strong>{String(questionCount).padStart(2, "0")}</strong>
                <span>THINGS LEARNED</span>
              </div>
            </div>
            <div className="feed-toolbar">
              <label className="search-box">
                <Search size={17} />
                <input
                  placeholder="Search your updates..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  aria-label="Search updates"
                />
                <span>⌘ K</span>
              </label>
            </div>
            <div className="list-heading">
              <span>
                {filtered.length}{" "}
                {view === "questions" ? "CONVERSATIONS" : "UPDATES"}
                {filtered.length > 0 && (
                  <span className="page-range">
                    {" "}· showing {pageStart}-{pageEnd}
                  </span>
                )}
              </span>
              <span>
                MOST RECENT <ArrowDownRight size={13} />
              </span>
            </div>
            <div className="update-list">
              {loading ? (
                <div className="loading-list">Loading your updates…</div>
              ) : error ? (
                <div className="list-error">
                  <CircleHelp size={20} />
                  <strong>Could not load updates</strong>
                  <p>{error}</p>
                </div>
              ) : filtered.length ? (
                pagedFiltered.map((item) => (
                  <button
                    key={item.id}
                    className={`update-row ${selected?.id === item.id ? "selected" : ""}`}
                    onClick={() => {
                      setSelectedId(item.id);
                      setMobileDetail(true);
                    }}
                  >
                    <div className="row-top">
                      <span className="row-repo">
                        <span className="mini-repo-icon">
                          {initials(repoName(item.repo_url))}
                        </span>
                        {repoName(item.repo_url)}
                      </span>
                      <span className="row-date">
                        {relativeDate(item.shipped_at)}
                      </span>
                    </div>
                    <h3>{item.title}</h3>
                    <p>{item.summary}</p>
                    <div className="row-bottom">
                      <div>
                        {item.tags.slice(0, 2).map((tag) => (
                          <span className="tag" key={tag}>
                            {tag}
                          </span>
                        ))}
                        {item.questions.length > 0 && (
                          <span className="question-count">
                            <MessageCircle size={13} /> {item.questions.length}
                          </span>
                        )}
                      </div>
                      <ArrowUpRight size={17} />
                    </div>
                  </button>
                ))
              ) : updates.length === 0 ? (
                <EmptyState
                  onSetup={() => setSetupOpen(true)}
                  onNew={() => setNewOpen(true)}
                />
              ) : (
                <div className="no-matches">
                  <Search size={24} />
                  <h3>No matching updates</h3>
                  <p>Try a different search or repository.</p>
                  <button
                    onClick={() => {
                      setSearch("");
                      setRepo("All updates");
                      setView("updates");
                    }}
                  >
                    Clear filters
                  </button>
                </div>
              )}
            </div>
            {filtered.length > UPDATES_PAGE_SIZE && (
              <div className="pagination" aria-label="Updates pagination">
                <button
                  className="page-btn"
                  disabled={safeUpdatePage <= 1}
                  onClick={() => setUpdatesPage((p) => Math.max(1, p - 1))}
                  aria-label="Previous page"
                >
                  <ArrowLeft size={14} /> Prev
                </button>
                <span className="page-info">
                  Page {safeUpdatePage} of {totalUpdatePages}
                </span>
                <div className="page-numbers">
                  {Array.from({ length: totalUpdatePages }, (_, i) => i + 1)
                    .filter((n) => n === 1 || n === totalUpdatePages || Math.abs(n - safeUpdatePage) <= 1)
                    .reduce<(number | "gap")[]>((acc, n, idx, arr) => {
                      if (idx > 0 && n - (arr[idx - 1] as number) > 1) acc.push("gap");
                      acc.push(n);
                      return acc;
                    }, [])
                    .map((n, idx) =>
                      n === "gap" ? (
                        <span key={"gap-" + idx} className="page-gap">
                          …
                        </span>
                      ) : (
                        <button
                          key={n}
                          className={"page-num" + (n === safeUpdatePage ? " active" : "")}
                          onClick={() => setUpdatesPage(n as number)}
                          aria-label={"Go to page " + n}
                          aria-current={n === safeUpdatePage ? "page" : undefined}
                        >
                          {n}
                        </button>
                      ),
                    )}
                </div>
                <button
                  className="page-btn"
                  disabled={safeUpdatePage >= totalUpdatePages}
                  onClick={() => setUpdatesPage((p) => Math.min(totalUpdatePages, p + 1))}
                  aria-label="Next page"
                >
                  Next <ArrowRight size={14} />
                </button>
              </div>
            )}
          </section>
          <section className="detail-panel" aria-label="Update details">
            {selected ? (
              <UpdateDetail
                update={selected}
                token={token}
                onQuestion={addQuestion}
                onImpact={addImpact}
                onRefresh={refreshUpdate}
                onBack={() => setMobileDetail(false)}
              />
            ) : (
              <div className="detail-placeholder">
                <div className="placeholder-symbol">
                  <Inbox size={27} />
                </div>
                <span>NOTHING SELECTED</span>
                <h2>Context lives here.</h2>
                <p>Choose an update to revisit the story behind the code.</p>
              </div>
            )}
          </section>
            </>
          )}
        </div>
      </main>
      {setupOpen && <SetupModal close={() => setSetupOpen(false)} serverToken={token} />}
      {keysOpen && <KeysModal close={() => setKeysOpen(false)} token={token} />}
      {newOpen && (
        <NewModal
          close={() => setNewOpen(false)}
          save={addUpdate}
          saving={saving}
        />
      )}
    </div>
  );
}

function isWorkspacePath(): boolean {
  try {
    const path = window.location.pathname || "/";
    if (path === "/app" || path.startsWith("/app/")) return true;
    if (path === "/workspace" || path.startsWith("/workspace/")) return true;
    const params = new URLSearchParams(window.location.search);
    if (params.get("view") === "workspace" || params.get("view") === "app") return true;
    if (window.location.hash === "#/app" || window.location.hash.startsWith("#/workspace")) return true;
    return false;
  } catch {
    return false;
  }
}

export default function App() {
  const [workspace] = useState<boolean>(() => isWorkspacePath());
  useEffect(() => {
    const onPop = () => {
      try {
        // reload route on back/forward so marketing <-> workspace switch cleanly
        window.location.reload();
      } catch { /* ignore */ }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  if (!workspace) return <Homepage />;
  return <WorkspaceApp />;
}
