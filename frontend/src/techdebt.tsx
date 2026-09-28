import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  FileCode2,
  GitBranch,
  GitCommitHorizontal,
  Github,
  Inbox,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import type { NewTechDebt, TechDebt, TechDebtStatus, TechDebtUrgency } from "./types";
import { Button } from "./components/ui/button";
import "./techdebt.css";

const apiBase = (import.meta as any).env.VITE_API_BASE_URL || "";

async function api<T>(path: string, token: string, options?: RequestInit): Promise<T> {
  const response = await fetch(apiBase + "/api" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: "Bearer " + token } : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body.detail || ("Request failed (" + response.status + ")")) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return response.json() as Promise<T>;
}

const URGENCIES: TechDebtUrgency[] = ["low", "medium", "high", "critical"];
const STATUSES: TechDebtStatus[] = ["open", "in-progress", "resolved", "wont-fix"];

function urgencyLabel(u: string) {
  return u.toUpperCase();
}

function statusLabel(s: string) {
  if (s === "in-progress") return "IN PROGRESS";
  if (s === "wont-fix") return "WON'T FIX";
  return s.toUpperCase();
}

function repoShort(url: string) {
  try {
    const parts = new URL(url).pathname.replace(/\.git$/, "").split("/").filter(Boolean);
    if (parts.length >= 2) return parts[parts.length - 2] + "/" + parts[parts.length - 1];
    return parts[parts.length - 1] || url;
  } catch {
    return url;
  }
}

function dateLabel(date: string) {
  try {
    return new Date(date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return date;
  }
}

function relativeDate(date: string) {
  const days = Math.floor((Date.now() - new Date(date).getTime()) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return days + " days ago";
  return dateLabel(date);
}
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="form-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function TechDebtNewModal({ close, save, saving, defaultRepo }: { close: () => void; save: (v: NewTechDebt) => Promise<void>; saving: boolean; defaultRepo: string }) {
  const [form, setForm] = useState({
    title: "",
    scope: "",
    description: "",
    impact: "",
    mitigation: "",
    current_state: "",
    urgency: "medium" as TechDebtUrgency,
    repo_url: defaultRepo && defaultRepo !== "All repos" ? defaultRepo : "",
    file_path: "",
    files: "",
    tags: "",
    branch: "",
  });
  const [error, setError] = useState("");
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await save({
        title: form.title.trim(),
        scope: form.scope.trim(),
        description: form.description.trim(),
        impact: form.impact.trim(),
        mitigation: form.mitigation.trim(),
        current_state: form.current_state.trim(),
        repo_url: form.repo_url.trim(),
        urgency: form.urgency,
        file_path: form.file_path.trim(),
        files: form.files.split("\n").map((s) => s.trim()).filter(Boolean),
        tags: form.tags.split(",").map((s) => s.trim()).filter(Boolean),
        branch: form.branch.trim(),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save tech debt");
    }
  };
  return (
    <div className="modal-backdrop" onMouseDown={close}>
      <div className="modal new-modal" role="dialog" aria-modal="true" aria-label="New tech debt" onMouseDown={(e) => e.stopPropagation()}>
        <button className="icon-button modal-close" aria-label="Close" onClick={close}>
          <X size={18} />
        </button>
        <h2>Log tech debt</h2>
        <p className="modal-intro">Capture the shortcut now so the fix is obvious later. Fields match what /tech-depth sends.</p>
        <form onSubmit={onSubmit}>
          <div className="td-modal-grid">
            <Field label="Title">
              <input required value={form.title} placeholder="e.g. Retry without idempotency key" onChange={(e) => set("title", e.target.value)} />
            </Field>
            <Field label="Scope (module / area)">
              <input required value={form.scope} placeholder="e.g. backend worker retry path" onChange={(e) => set("scope", e.target.value)} />
            </Field>
          </div>
          <div className="td-modal-grid">
            <Field label="Repository URL">
              <input required value={form.repo_url} placeholder="https://github.com/you/project" onChange={(e) => set("repo_url", e.target.value)} />
            </Field>
            <Field label="Urgency">
              <select value={form.urgency} onChange={(e) => set("urgency", e.target.value)}>
                {URGENCIES.map((u) => (
                  <option key={u} value={u}>{urgencyLabel(u)}</option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Description — what was rushed or cut short">
            <textarea required value={form.description} placeholder="What is the debt? Where does it live?" onChange={(e) => set("description", e.target.value)} />
          </Field>
          <Field label="Impact on the current code">
            <textarea required value={form.impact} placeholder="Bugs, perf, maintainability, risk…" onChange={(e) => set("impact", e.target.value)} />
          </Field>
          <Field label="How to mitigate">
            <textarea required value={form.mitigation} placeholder="The proper fix, step by step" onChange={(e) => set("mitigation", e.target.value)} />
          </Field>
          <Field label="What is solved / covered currently">
            <textarea required value={form.current_state} placeholder="Workaround, passing tests, manual cleanup…" onChange={(e) => set("current_state", e.target.value)} />
          </Field>
          <div className="td-modal-grid">
            <Field label="Primary file">
              <input value={form.file_path} placeholder="backend/worker.py" onChange={(e) => set("file_path", e.target.value)} />
            </Field>
            <Field label="Branch">
              <input value={form.branch} placeholder="main" onChange={(e) => set("branch", e.target.value)} />
            </Field>
          </div>
          <div className="td-modal-grid">
            <Field label="Related files (one per line)">
              <textarea value={form.files} placeholder={"backend/worker.py\nbackend/queue.py"} onChange={(e) => set("files", e.target.value)} />
            </Field>
            <Field label="Tags (comma separated)">
              <input value={form.tags} placeholder="reliability, retry" onChange={(e) => set("tags", e.target.value)} />
            </Field>
          </div>
          {error && <div className="td-form-error">{error}</div>}
          <div className="modal-footer">
            <button type="button" className="button subtle" onClick={close}>Cancel</button>
            <Button type="submit" className="button primary" disabled={saving}>{saving ? "Saving…" : "Save tech debt"}</Button>
          </div>
        </form>
      </div>
    </div>
  );
}
function TechDebtDetail({ item, token, onChanged, onDeleted }: { item: TechDebt; token: string; onChanged: (t: TechDebt) => void; onDeleted: (id: string) => void }) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const setStatus = async (status: TechDebtStatus) => {
    setBusy(status);
    setError("");
    try {
      const next = await api<TechDebt>("/tech-debt/" + item.id, token, { method: "PATCH", body: JSON.stringify({ status }) });
      onChanged(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update status");
    } finally {
      setBusy("");
    }
  };
  const remove = async () => {
    if (!window.confirm("Delete this tech-debt item?")) return;
    setBusy("delete");
    try {
      await api<{ ok: boolean }>("/tech-debt/" + item.id, token, { method: "DELETE" });
      onDeleted(item.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete");
      setBusy("");
    }
  };
  return (
    <div className="td-detail-scroll">
      <div className="td-badges">
        <span className={"td-urgency " + item.urgency}>{urgencyLabel(item.urgency)} urgency</span>
        <span className={"td-status " + item.status}>{statusLabel(item.status)}</span>
      </div>
      <h1>{item.title}</h1>
      <div className="td-scope-line">
        <FileCode2 size={14} />
        <span>{item.scope}</span>
      </div>
      <div className="td-meta-grid">
        <span className="td-meta-chip">
          <Github size={13} />
          <a href={item.repo_url} target="_blank" rel="noreferrer">{repoShort(item.repo_url)}</a>
        </span>
        {item.file_path && (
          <span className="td-meta-chip"><FileCode2 size={13} /> {item.file_path}</span>
        )}
        {item.branch && (
          <span className="td-meta-chip"><GitBranch size={13} /> {item.branch}</span>
        )}
        {item.commit_sha && (
          <span className="td-meta-chip" title={item.commit_sha}><GitCommitHorizontal size={13} /> {item.commit_sha.slice(0, 7)}</span>
        )}
        {item.author_agent && (
          <span className="td-meta-chip"><Sparkles size={13} /> {item.author_agent}</span>
        )}
        <span className="td-meta-chip">Found {relativeDate(item.created_at)}</span>
        {item.resolved_at && (
          <span className="td-meta-chip"><Check size={13} /> Resolved {dateLabel(item.resolved_at)}</span>
        )}
      </div>
      <section className="td-section">
        <div className="td-section-head"><span className="td-section-num">01</span><h3>Description</h3></div>
        <p>{item.description}</p>
      </section>
      <section className="td-section">
        <div className="td-section-head"><span className="td-section-num">02</span><h3>Impact on the current code</h3></div>
        <p>{item.impact}</p>
      </section>
      <section className="td-section">
        <div className="td-section-head"><span className="td-section-num">03</span><h3>How to mitigate</h3></div>
        <div className="td-callout mitigate">
          <strong><Wrench size={13} /> PROPER FIX</strong>
          <div style={{ whiteSpace: "pre-wrap" }}>{item.mitigation}</div>
        </div>
      </section>
      <section className="td-section">
        <div className="td-section-head"><span className="td-section-num">04</span><h3>What is solved currently</h3></div>
        <div className="td-callout covered">
          <strong><ShieldCheck size={13} /> COVERED TODAY</strong>
          <div style={{ whiteSpace: "pre-wrap" }}>{item.current_state}</div>
        </div>
      </section>
      {(item.files.length > 0 || (item.tags && item.tags.length > 0)) && (
        <section className="td-section">
          <div className="td-section-head"><span className="td-section-num">05</span><h3>Files and tags</h3></div>
          {item.files.length > 0 && (
            <div className="td-tags">
              {item.files.map((f) => (
                <span className="td-tag" key={f}>{f}</span>
              ))}
            </div>
          )}
          {item.tags && item.tags.length > 0 && (
            <div className="td-tags">
              {item.tags.map((t) => (
                <span className="td-tag" key={t}>#{t}</span>
              ))}
            </div>
          )}
        </section>
      )}
      <div className="td-actions">
        {item.status === "open" && (
          <button className="td-btn primary" disabled={!!busy} onClick={() => setStatus("in-progress")}>Start fixing</button>
        )}
        {item.status !== "resolved" && (
          <button className="td-btn" disabled={!!busy} onClick={() => setStatus("resolved")}><Check size={14} /> Mark resolved</button>
        )}
        {item.status !== "in-progress" && item.status !== "resolved" && item.status !== "wont-fix" && null}
        {item.status === "resolved" ? (
          <button className="td-btn" disabled={!!busy} onClick={() => setStatus("open")}>Reopen</button>
        ) : item.status !== "wont-fix" ? (
          <button className="td-btn" disabled={!!busy} onClick={() => setStatus("wont-fix")}>Won't fix</button>
        ) : (
          <button className="td-btn" disabled={!!busy} onClick={() => setStatus("open")}>Reopen</button>
        )}
        {item.status === "open" || item.status === "wont-fix" ? null : null}
        <button className="td-btn danger" disabled={busy === "delete"} onClick={remove}><Trash2 size={14} /> Delete</button>
      </div>
      {error && <div className="td-form-error">{error}</div>}
      {busy && busy !== "delete" && <div className="td-count">Updating…</div>}
    </div>
  );
}
export function TechDebtView({ token, repos }: { token: string; repos: string[] }) {
  const [items, setItems] = useState<TechDebt[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [repo, setRepo] = useState("All repos");
  const [urgency, setUrgency] = useState("all");
  const [status, setStatus] = useState("open-all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [newOpen, setNewOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api<TechDebt[]>("/tech-debt", token);
      setItems(data);
      setSelectedId((c) => (c && data.some((d) => d.id === c) ? c : data[0]?.id || null));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load tech debt");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  const openCount = items.filter((i) => i.status === "open" || i.status === "in-progress").length;
  const hotCount = items.filter((i) => (i.urgency === "high" || i.urgency === "critical") && i.status !== "resolved" && i.status !== "wont-fix").length;
  const progressCount = items.filter((i) => i.status === "in-progress").length;
  const resolvedCount = items.filter((i) => i.status === "resolved").length;

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return items.filter((i) => {
      if (repo !== "All repos" && i.repo_url !== repo) return false;
      if (urgency !== "all" && i.urgency !== urgency) return false;
      if (status === "open-all") {
        if (i.status === "resolved" || i.status === "wont-fix") return false;
      } else if (status !== "all" && i.status !== status) return false;
      if (!q) return true;
      const hay = (i.title + " " + i.scope + " " + i.description + " " + i.impact + " " + i.mitigation + " " + (i.file_path || "") + " " + i.tags.join(" ")).toLowerCase();
      return hay.includes(q);
    });
  }, [items, search, repo, urgency, status]);

  const selected = filtered.find((i) => i.id === selectedId) || filtered[0] || null;

  const create = async (v: NewTechDebt) => {
    setSaving(true);
    try {
      const created = await api<TechDebt>("/tech-debt", token, { method: "POST", body: JSON.stringify(v) });
      setItems((c) => [created, ...c]);
      setSelectedId(created.id);
      setNewOpen(false);
      setSearch("");
      setRepo("All repos");
      setUrgency("all");
      setStatus("open-all");
    } finally {
      setSaving(false);
    }
  };

  const changed = (t: TechDebt) => setItems((c) => c.map((i) => (i.id === t.id ? t : i)));
  const deleted = (id: string) => {
    setItems((c) => {
      const next = c.filter((i) => i.id !== id);
      setSelectedId((s) => (s === id ? next[0]?.id || null : s));
      return next;
    });
  };

  const repoOptions = ["All repos", ...Array.from(new Set([...repos, ...items.map((i) => i.repo_url)]))];

  return (
    <div className="td-wrap">
      <section className="td-list-panel">
        <div className="td-list-head">
          <div className="td-eyebrow"><span className="td-eyebrow-line" /> TECH DEBT INBOX</div>
          <h2>Tech debt</h2>
          <p>Shortcuts your agent found with /tech-depth — what hurts, how to fix it, and what holds for now.</p>
        </div>
        <div className="td-stats">
          <div className="td-stat"><strong>{String(openCount).padStart(2, "0")}</strong><span>OPEN</span></div>
          <div className="td-stat critical"><strong>{String(hotCount).padStart(2, "0")}</strong><span>HOT</span></div>
          <div className="td-stat progress"><strong>{String(progressCount).padStart(2, "0")}</strong><span>FIXING</span></div>
          <div className="td-stat resolved"><strong>{String(resolvedCount).padStart(2, "0")}</strong><span>FIXED</span></div>
        </div>
        <div className="td-filters">
          <label className="td-search">
            <Search size={15} />
            <input placeholder="Search debt, scope, files…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search tech debt" />
          </label>
          <div className="td-filter-row">
            <select value={repo} onChange={(e) => setRepo(e.target.value)} aria-label="Filter by repo">
              {repoOptions.map((r) => (
                <option key={r} value={r}>{r === "All repos" ? "All repos" : repoShort(r)}</option>
              ))}
            </select>
            <select value={urgency} onChange={(e) => setUrgency(e.target.value)} aria-label="Filter by urgency">
              <option value="all">Any urgency</option>
              {URGENCIES.map((u) => (
                <option key={u} value={u}>{urgencyLabel(u)}</option>
              ))}
            </select>
            <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
              <option value="open-all">Open + fixing</option>
              <option value="all">Everything</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>{statusLabel(s)}</option>
              ))}
            </select>
          </div>
          <div className="td-list-toolbar">
            <span className="td-count">{filtered.length} ITEMS</span>
            <button className="td-new-fab" onClick={() => setNewOpen(true)}><Plus size={14} /> Log debt</button>
          </div>
        </div>
        <div className="td-list">
          {loading ? (
            <div className="td-count">Loading tech debt…</div>
          ) : error ? (
            <div className="td-count">{error}</div>
          ) : filtered.length ? (
            filtered.map((i) => (
              <button key={i.id} className={"td-row" + (selected?.id === i.id ? " selected" : "")} onClick={() => setSelectedId(i.id)}>
                <div className="td-row-top">
                  <span className={"td-urgency " + i.urgency}>{i.urgency}</span>
                  <span className={"td-status " + i.status}>{statusLabel(i.status)}</span>
                </div>
                <h3>{i.title}</h3>
                <div className="td-row-scope">{i.scope}</div>
                <div className="td-row-meta">
                  <span>{repoShort(i.repo_url)}</span>
                  <span>{relativeDate(i.created_at)}</span>
                </div>
              </button>
            ))
          ) : (
            <div className="td-empty-detail">
              <AlertTriangle size={26} />
              <h2>No tech debt here</h2>
              <p>Run /tech-depth in your agent checkout, or log the first shortcut manually.</p>
              <p style={{ marginTop: 12 }}>
                <button className="td-new-fab" onClick={() => setNewOpen(true)}><Plus size={14} /> Log debt</button>
              </p>
            </div>
          )}
        </div>
      </section>
      <section className="td-detail-panel" aria-label="Tech debt details">
        {selected ? (
          <TechDebtDetail key={selected.id} item={selected} token={token} onChanged={changed} onDeleted={deleted} />
        ) : (
          <div className="td-empty-detail">
            <Inbox size={26} />
            <h2>Nothing selected</h2>
            <p>Pick a debt item to see its impact, mitigation, and current cover.</p>
          </div>
        )}
      </section>
      {newOpen && (
        <TechDebtNewModal close={() => setNewOpen(false)} save={create} saving={saving} defaultRepo={repo} />
      )}
    </div>
  );
}
