import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  Bell,
  Bug,
  Calendar,
  Check,
  ChevronDown,
  Code2,
  Copy,
  FileText,
  Flag,
  GitBranch,
  Lightbulb,
  ListTodo,
  MoreHorizontal,
  Pencil,
  Pin,
  Plus,
  Search,
  Sparkles,
  StickyNote,
  Terminal,
  Trash2,
  X,
} from "lucide-react";
import type { Note, NoteCategory, NoteColor, NotePriority, NoteStatus } from "./types";
import { Button } from "./components/ui/button";
import "./notes.css";

const apiBase = (import.meta as any).env.VITE_API_BASE_URL || "";
const FENCE = String.fromCharCode(96, 96, 96);

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

export const NOTE_COLORS: { value: NoteColor; label: string; swatch: string; accent: string }[] = [
  { value: "default", label: "Default", swatch: "#d8d8d2", accent: "#8a8f85" },
  { value: "red", label: "Red", swatch: "#e88f8f", accent: "#d64545" },
  { value: "orange", label: "Orange", swatch: "#eab676", accent: "#c97a1a" },
  { value: "yellow", label: "Yellow", swatch: "#e3cf5a", accent: "#a68a00" },
  { value: "green", label: "Green", swatch: "#7fce7f", accent: "#2f9e44" },
  { value: "blue", label: "Blue", swatch: "#7fa8e8", accent: "#2f6fd6" },
  { value: "purple", label: "Purple", swatch: "#b394e8", accent: "#7048d6" },
  { value: "pink", label: "Pink", swatch: "#e88bb4", accent: "#d6336c" },
];

const CATEGORY_ORDER: NoteCategory[] = ["todo", "bug", "idea", "investigation", "implementation", "command", "decision", "follow-up", "general"];

const CATEGORY_LABEL: Record<NoteCategory, string> = {
  todo: "TODO",
  bug: "BUG",
  idea: "IDEA",
  investigation: "INVESTIGATION",
  implementation: "IMPLEMENTATION",
  command: "COMMAND",
  decision: "DECISION",
  "follow-up": "FOLLOW-UP",
  general: "GENERAL",
};

const CATEGORY_ICON: Record<NoteCategory, typeof Bug> = {
  todo: ListTodo,
  bug: Bug,
  idea: Lightbulb,
  investigation: Search,
  implementation: Code2,
  command: Terminal,
  decision: Flag,
  "follow-up": Bell,
  general: FileText,
};

const STATUS_LABEL: Record<NoteStatus, string> = {
  open: "OPEN",
  "in-progress": "IN PROGRESS",
  done: "DONE",
  archived: "ARCHIVED",
};

const PRIORITY_ORDER: Record<NotePriority, number> = { none: 0, low: 1, medium: 2, high: 3 };

type SortKey = "updated" | "created" | "oldest" | "priority" | "category" | "title";
type GroupKey = "none" | "date" | "category" | "status" | "repository";
type DatePreset = "all" | "today" | "yesterday" | "last7" | "last30" | "month" | "custom";
type DateField = "updated_at" | "created_at" | "due_date";

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "updated", label: "Recently updated" },
  { value: "created", label: "Recently created" },
  { value: "oldest", label: "Oldest" },
  { value: "priority", label: "Priority" },
  { value: "category", label: "Category" },
  { value: "title", label: "Title" },
];

const DATE_OPTIONS: { value: DatePreset; label: string }[] = [
  { value: "all", label: "Any date" },
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "last7", label: "Last 7 days" },
  { value: "last30", label: "Last 30 days" },
  { value: "month", label: "This month" },
  { value: "custom", label: "Custom range" },
];

export function normalizeNote(raw: any): Note {
  const cats: string[] = ["todo", "bug", "idea", "investigation", "implementation", "command", "decision", "follow-up", "general"];
  const stats: string[] = ["open", "in-progress", "done", "archived"];
  const pris: string[] = ["none", "low", "medium", "high"];
  return {
    id: String(raw.id || ""),
    title: String(raw.title || "Untitled"),
    content: String(raw.content || ""),
    color: (raw.color as NoteColor) || "default",
    category: cats.indexOf(raw.category) !== -1 ? raw.category : "general",
    status: stats.indexOf(raw.status) !== -1 ? raw.status : "open",
    priority: pris.indexOf(raw.priority) !== -1 ? raw.priority : "none",
    tags: Array.isArray(raw.tags) ? raw.tags.map((t: any) => String(t)) : [],
    repository: raw.repository || null,
    branch: raw.branch || null,
    file_path: raw.file_path || null,
    commit_hash: raw.commit_hash || null,
    related_url: raw.related_url || null,
    due_date: raw.due_date || null,
    pinned: Boolean(raw.pinned),
    archived: Boolean(raw.archived) || raw.status === "archived",
    created_at: raw.created_at,
    updated_at: raw.updated_at,
  };
}

export function noteRef(note: Note): string {
  const hex = note.id.replace(/-/g, "").slice(0, 4).toUpperCase() || "0000";
  return "N-" + hex;
}

function fullDate(value: string | null): string {
  if (!value) return "No date";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "No date";
  return d.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

function relativeTime(value: string | null): string {
  if (!value) return "No date";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "No date";
  const diff = Date.now() - then;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "Just now";
  if (min < 60) return min + " min ago";
  const hrs = Math.floor(min / 60);
  if (hrs < 24) return hrs + " h ago";
  const days = Math.floor(hrs / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return days + " days ago";
  return new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function dayKey(d: Date): string {
  const m = String(d.getMonth() + 1);
  const day = String(d.getDate());
  return d.getFullYear() + "-" + (m.length === 1 ? "0" + m : m) + "-" + (day.length === 1 ? "0" + day : day);
}

function dateInPreset(value: string | null, preset: DatePreset, from: string, to: string): boolean {
  if (preset === "all") return true;
  if (!value) return false;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return false;
  const now = new Date();
  if (preset === "today") return dayKey(d) === dayKey(now);
  if (preset === "yesterday") {
    const y = new Date(now);
    y.setDate(now.getDate() - 1);
    return dayKey(d) === dayKey(y);
  }
  if (preset === "last7") return Date.now() - d.getTime() <= 7 * 86400000 && d.getTime() <= Date.now();
  if (preset === "last30") return Date.now() - d.getTime() <= 30 * 86400000 && d.getTime() <= Date.now();
  if (preset === "month") return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
  if (preset === "custom") {
    if (from) {
      const f = new Date(from + "T00:00:00");
      if (!Number.isNaN(f.getTime()) && d < f) return false;
    }
    if (to) {
      const t = new Date(to + "T23:59:59");
      if (!Number.isNaN(t.getTime()) && d > t) return false;
    }
    return true;
  }
  return true;
}

function accentFor(note: Note): string {
  const found = NOTE_COLORS.find((c) => c.value === note.color);
  return found ? found.accent : "#8a8f85";
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function inlineMd(s: string): string {
  const BT = String.fromCharCode(96);
  let out = escapeHtml(s);
  const codeRe = new RegExp(BT + "([^" + BT + "]+)" + BT, "g");
  out = out.replace(codeRe, "<code class=\"md-code\">$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, "<a href=\"$2\" target=\"_blank\" rel=\"noreferrer\">$1</a>");
  return out;
}

function CodeBlock({ code, lang }: { code: string; lang: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      const field = document.createElement("textarea");
      field.value = code;
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      try { document.execCommand("copy"); } catch { /* noop */ }
      field.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };
  return (
    <div className="md-codeblock">
      <div className="md-codeblock-bar">
        <span>{lang || "code"}</span>
        <button type="button" onClick={copy} aria-label="Copy code block">
          {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

function Markdown({ text, command }: { text: string; command?: boolean }) {
  const blocks = useMemo(() => {
    const out: { key: string; kind: string; code?: string; lang?: string; html?: string }[] = [];
    const parts = text.split(FENCE);
    let htmlBuf: string[] = [];
    const flush = () => {
      if (!htmlBuf.length) return;
      const lines = htmlBuf.join("\n").split("\n");
      let html = "";
      let inList = false;
      for (const line of lines) {
        const check = line.match(/^\s*- \[( |x|X)\] (.*)$/);
        if (check) {
          if (!inList) { html += "<ul class=\"md-list\">"; inList = true; }
          const done = check[1].toLowerCase() === "x";
          html += "<li class=\"md-check\"><span class=\"md-box\" data-done=\"" + (done ? "1" : "0") + "\">" + (done ? "&#10003;" : "") + "</span><span>" + inlineMd(check[2]) + "</span></li>";
          continue;
        }
        const bullet = line.match(/^\s*[-*] (.*)$/);
        if (bullet) {
          if (!inList) { html += "<ul class=\"md-list\">"; inList = true; }
          html += "<li>" + inlineMd(bullet[1]) + "</li>";
          continue;
        }
        if (inList) { html += "</ul>"; inList = false; }
        if (!line.trim()) continue;
        html += "<p>" + inlineMd(line) + "</p>";
      }
      if (inList) html += "</ul>";
      if (html) out.push({ key: "h" + out.length, kind: "html", html });
      htmlBuf = [];
    };
    parts.forEach((part, idx) => {
      if (idx % 2 === 1) {
        flush();
        const nl = part.indexOf("\n");
        const lang = (nl === -1 ? part.trim().slice(0, 12) : part.slice(0, nl).trim().slice(0, 12)) || "code";
        const code = nl === -1 ? part : part.slice(nl + 1);
        out.push({ key: "c" + out.length, kind: "code", code, lang });
      } else {
        htmlBuf.push(part);
      }
    });
    flush();
    return out;
  }, [text]);
  if (!text.trim()) return null;
  if (command) {
    const hasFence = text.indexOf(FENCE) !== -1;
    if (!hasFence) {
      return (
        <div className="md-command">
          <pre><code>{text.trim()}</code></pre>
        </div>
      );
    }
  }
  return (
    <div className="md-body">
      {blocks.map((b) =>
        b.kind === "code" ? (
          <CodeBlock key={b.key} code={b.code || ""} lang={b.lang || ""} />
        ) : (
          <div key={b.key} dangerouslySetInnerHTML={{ __html: b.html || "" }} />
        ),
      )}
    </div>
  );
}

type ComposerDraft = {
  title: string;
  content: string;
  category: NoteCategory;
  status: NoteStatus;
  priority: NotePriority;
  tags: string;
  repository: string;
  branch: string;
  file_path: string;
  commit_hash: string;
  related_url: string;
  due_date: string;
  color: NoteColor;
};

const EMPTY_DRAFT: ComposerDraft = {
  title: "",
  content: "",
  category: "general",
  status: "open",
  priority: "none",
  tags: "",
  repository: "",
  branch: "",
  file_path: "",
  commit_hash: "",
  related_url: "",
  due_date: "",
  color: "default",
};

function draftFromNote(n: Note): ComposerDraft {
  return {
    title: n.title,
    content: n.content,
    category: n.category,
    status: n.status === "archived" ? "open" : n.status,
    priority: n.priority,
    tags: (n.tags || []).join(", "),
    repository: n.repository || "",
    branch: n.branch || "",
    file_path: n.file_path || "",
    commit_hash: n.commit_hash || "",
    related_url: n.related_url || "",
    due_date: n.due_date ? n.due_date.slice(0, 10) : "",
    color: n.color,
  };
}

function parseTagsInput(input: string): string[] {
  const out: string[] = [];
  input.split(",").forEach((raw) => {
    const t = raw.trim().toLowerCase().replace(/\s+/g, "-").slice(0, 40);
    if (t && out.indexOf(t) === -1) out.push(t);
  });
  return out.slice(0, 20);
}

function draftToPayload(d: ComposerDraft) {
  return {
    title: d.title.trim(),
    content: d.content.trim(),
    category: d.category,
    status: d.status,
    priority: d.priority,
    tags: parseTagsInput(d.tags),
    repository: d.repository.trim() || null,
    branch: d.branch.trim() || null,
    file_path: d.file_path.trim() || null,
    commit_hash: d.commit_hash.trim() || null,
    related_url: d.related_url.trim() || null,
    due_date: d.due_date ? new Date(d.due_date + "T12:00:00").toISOString() : null,
    color: d.color,
  };
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

function agentContextText(n: Note): string {
  const linesOut: string[] = [];
  linesOut.push("Note " + noteRef(n) + ": " + n.title);
  linesOut.push("Category: " + n.category + " | Status: " + n.status + " | Priority: " + n.priority);
  if (n.repository) linesOut.push("Repository: " + n.repository);
  if (n.branch) linesOut.push("Branch: " + n.branch);
  if (n.file_path) linesOut.push("Path: " + n.file_path);
  if (n.commit_hash) linesOut.push("Commit: " + n.commit_hash);
  if ((n.tags || []).length) linesOut.push("Tags: " + n.tags.join(", "));
  linesOut.push("");
  linesOut.push(n.content || "(no description)");
  return linesOut.join("\n");
}

function previewText(content: string, max = 160): string {
  const flat = content.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  return flat.slice(0, max - 1).trim() + "\u2026";
}

function CategoryPill({ value, onClick }: { value: NoteCategory; onClick?: () => void }) {
  const Icon = CATEGORY_ICON[value];
  const inner = (
    <span className="ticket-cat" data-cat={value}>
      <Icon size={12} /> {CATEGORY_LABEL[value]}
    </span>
  );
  if (!onClick) return inner;
  return (
    <button type="button" className="pill-button" onClick={(e) => { e.stopPropagation(); onClick(); }} title={"Filter by " + CATEGORY_LABEL[value]} aria-label={"Filter by category " + CATEGORY_LABEL[value]}>
      {inner}
    </button>
  );
}

function StatusDot({ value }: { value: NoteStatus }) {
  return <span className="status-dot2" data-status={value} aria-hidden="true" />;
}

function TicketCard({ note, selected, onOpen, onFilterCategory, onFilterTag, onTogglePin, onToggleDone, onMenu, menuOpen, onEdit, onDuplicate, onArchive, onDelete, onCopyRef, onCopyAgent, busy }: {
  note: Note;
  selected: boolean;
  onOpen: () => void;
  onFilterCategory: () => void;
  onFilterTag: (t: string) => void;
  onTogglePin: () => void;
  onToggleDone: () => void;
  onMenu: () => void;
  menuOpen: boolean;
  onEdit: () => void;
  onDuplicate: () => void;
  onArchive: () => void;
  onDelete: () => void;
  onCopyRef: () => void;
  onCopyAgent: () => void;
  busy: boolean;
}) {
  const done = note.status === "done";
  return (
    <article className={"ticket-card" + (selected ? " is-selected" : "") + (done ? " is-done" : "")} data-category={note.category} data-status={note.status} style={{ "--ticket-accent": accentFor(note) } as any} onClick={onOpen} tabIndex={0} role="button" aria-label={note.title} onKeyDown={(e) => { if (e.key === "Enter" && e.target === e.currentTarget) onOpen(); }}>
      <span className="ticket-accent" aria-hidden="true" />
      <div className="ticket-main">
        <div className="ticket-top">
          <CategoryPill value={note.category} onClick={onFilterCategory} />
          <span className="ticket-ref" title={"Note ID " + note.id}>{noteRef(note)}</span>
          {note.pinned ? <span className="ticket-pin" title="Pinned"><Pin size={12} /></span> : null}
          <span className="ticket-title">{note.title}</span>
          <span className="ticket-top-right">
            <span className="ticket-status" data-status={note.status} title={"Status: " + note.status}>
              <StatusDot value={note.status} /> {STATUS_LABEL[note.status]}
            </span>
            {note.priority !== "none" ? <span className="ticket-priority" data-p={note.priority} title={"Priority: " + note.priority}><Flag size={11} /> {note.priority}</span> : null}
            <button type="button" className={"ticket-quick" + (note.pinned ? " is-on" : "")} onClick={(e) => { e.stopPropagation(); onTogglePin(); }} disabled={busy} title={note.pinned ? "Unpin" : "Pin"} aria-label={note.pinned ? "Unpin note" : "Pin note"}><Pin size={14} /></button>
            <button type="button" className={"ticket-quick" + (done ? " is-on" : "")} onClick={(e) => { e.stopPropagation(); onToggleDone(); }} disabled={busy} title={done ? "Reopen" : "Mark done"} aria-label={done ? "Reopen note" : "Mark note done"}><Check size={14} /></button>
            <span className="ticket-menu-wrap">
              <button type="button" className="ticket-quick" onClick={(e) => { e.stopPropagation(); onMenu(); }} aria-label="Note actions" aria-haspopup="menu" aria-expanded={menuOpen}><MoreHorizontal size={15} /></button>
              {menuOpen ? (
                <span className="ticket-menu" role="menu" onClick={(e) => e.stopPropagation()}>
                  <button type="button" onClick={onEdit}><Pencil size={13} /> Edit</button>
                  <button type="button" onClick={onDuplicate}><Copy size={13} /> Duplicate</button>
                  <button type="button" onClick={onTogglePin}><Pin size={13} /> {note.pinned ? "Unpin" : "Pin"}</button>
                  <button type="button" onClick={onToggleDone}><Check size={13} /> {done ? "Reopen" : "Mark done"}</button>
                  <button type="button" onClick={onArchive}><Archive size={13} /> {note.archived || note.status === "archived" ? "Unarchive" : "Archive"}</button>
                  <button type="button" onClick={onCopyRef}><Copy size={13} /> Copy reference</button>
                  <button type="button" onClick={onCopyAgent}><Sparkles size={13} /> Copy agent context</button>
                  <button type="button" className="danger" onClick={onDelete}><Trash2 size={13} /> Delete</button>
                </span>
              ) : null}
            </span>
          </span>
        </div>
        {note.content ? (
          note.category === "command" ? (
            <div className="ticket-cmd" onClick={(e) => e.stopPropagation()}><code>{previewText(note.content, 220)}</code></div>
          ) : (
            <p className="ticket-preview">{previewText(note.content)}</p>
          )
        ) : null}
        <div className="ticket-meta">
          <span className="ticket-tags">
            {(note.tags || []).slice(0, 4).map((t) => (
              <button key={t} type="button" className="tag-chip" onClick={(e) => { e.stopPropagation(); onFilterTag(t); }} title={"Filter by tag " + t}>{t}</button>
            ))}
            {(note.tags || []).length > 4 ? <span className="tag-more">+{(note.tags || []).length - 4}</span> : null}
          </span>
          {note.repository ? <span className="ticket-repo" title={"Repository: " + note.repository}><GitBranch size={12} /> {note.repository}</span> : null}
          {note.due_date ? <span className="ticket-due" title={"Follow-up: " + fullDate(note.due_date)}><Calendar size={12} /> {relativeTime(note.due_date)}</span> : null}
          <span className="ticket-dates" title={"Updated: " + fullDate(note.updated_at) + "  |  Created: " + fullDate(note.created_at)}>Updated {relativeTime(note.updated_at)}</span>
        </div>
      </div>
    </article>
  );
}

function ComposerModal({ initial, repositories, saving, error, onClose, onSave }: {
  initial: ComposerDraft;
  repositories: string[];
  saving: boolean;
  error: string;
  onClose: () => void;
  onSave: (d: ComposerDraft) => void;
}) {
  const [d, setD] = useState<ComposerDraft>(initial);
  const [advanced, setAdvanced] = useState(Boolean(initial.branch || initial.file_path || initial.commit_hash || initial.related_url));
  const titleRef = useRef<HTMLInputElement>(null);
  useEffect(() => { setD(initial); }, [initial.title, initial.content]);
  useEffect(() => { window.setTimeout(() => titleRef.current?.focus(), 60); }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        if (d.title.trim()) onSave(d);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [d, onClose, onSave]);
  const set = (patch: Partial<ComposerDraft>) => setD((cur) => ({ ...cur, ...patch }));
  const submit = (e: FormEvent) => { e.preventDefault(); if (d.title.trim() && !saving) onSave(d); };
  return (
    <div className="ticket-modal-backdrop" onMouseDown={onClose}>
      <div className="ticket-modal" role="dialog" aria-modal="true" aria-label="Note composer" onMouseDown={(e) => e.stopPropagation()}>
        <div className="ticket-modal-head">
          <div>
            <div className="ticket-modal-eyebrow">DEVELOPER NOTE</div>
            <h3>{initial.title ? "Edit note" : "New note"}</h3>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close composer"><X size={17} /></button>
        </div>
        <form onSubmit={submit} className="ticket-form">
          <label className="ticket-field full">
            <span>Title</span>
            <input ref={titleRef} value={d.title} maxLength={180} placeholder="Fix tool-call retry handling" onChange={(e) => set({ title: e.target.value })} required />
          </label>
          <div className="ticket-grid-3">
            <label className="ticket-field">
              <span>Type</span>
              <select value={d.category} onChange={(e) => set({ category: e.target.value as NoteCategory })} aria-label="Note type">
                {CATEGORY_ORDER.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
              </select>
            </label>
            <label className="ticket-field">
              <span>Status</span>
              <select value={d.status} onChange={(e) => set({ status: e.target.value as NoteStatus })} aria-label="Note status">
                <option value="open">Open</option>
                <option value="in-progress">In progress</option>
                <option value="done">Done</option>
              </select>
            </label>
            <label className="ticket-field">
              <span>Priority</span>
              <select value={d.priority} onChange={(e) => set({ priority: e.target.value as NotePriority })} aria-label="Note priority">
                <option value="none">None</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </label>
          </div>
          <label className="ticket-field full">
            <span>Description <em>Markdown, code fences, checklists supported</em></span>
            <textarea value={d.content} rows={5} maxLength={10000} placeholder="Retry logic can duplicate tool execution when..." onChange={(e) => set({ content: e.target.value })} />
          </label>
          <div className="ticket-grid-2">
            <label className="ticket-field">
              <span>Tags <em>comma separated</em></span>
              <input value={d.tags} placeholder="backend, agent-runtime" onChange={(e) => set({ tags: e.target.value })} />
            </label>
            <label className="ticket-field">
              <span>Repository</span>
              <input value={d.repository} list="ticket-repos" placeholder="ai-voice-agent or personal" onChange={(e) => set({ repository: e.target.value })} />
              <datalist id="ticket-repos">{repositories.map((r) => <option key={r} value={r} />)}</datalist>
            </label>
          </div>
          <div className="ticket-grid-2">
            <label className="ticket-field">
              <span>Follow-up date</span>
              <input type="date" value={d.due_date} onChange={(e) => set({ due_date: e.target.value })} />
            </label>
            <div className="ticket-field">
              <span>Accent</span>
              <div className="accent-row">
                {NOTE_COLORS.map((c) => (
                  <button key={c.value} type="button" className={"accent-dot" + (d.color === c.value ? " active" : "")} style={{ background: c.swatch }} title={c.label} aria-label={"Accent " + c.label} aria-pressed={d.color === c.value} onClick={() => set({ color: c.value })} />
                ))}
              </div>
            </div>
          </div>
          <button type="button" className="advanced-toggle" onClick={() => setAdvanced((v) => !v)} aria-expanded={advanced}>
            Advanced context {advanced ? <ChevronDown size={14} /> : <ChevronDown size={14} className="rot" />}
          </button>
          {advanced ? (
            <div className="ticket-grid-2">
              <label className="ticket-field"><span>Branch</span><input value={d.branch} placeholder="fix/orchestrator-return" onChange={(e) => set({ branch: e.target.value })} /></label>
              <label className="ticket-field"><span>File path</span><input value={d.file_path} placeholder="src/runtime/swarm.ts" onChange={(e) => set({ file_path: e.target.value })} /></label>
              <label className="ticket-field"><span>Commit</span><input value={d.commit_hash} placeholder="abc1234" onChange={(e) => set({ commit_hash: e.target.value })} /></label>
              <label className="ticket-field"><span>Related URL</span><input value={d.related_url} placeholder="https://..." onChange={(e) => set({ related_url: e.target.value })} /></label>
            </div>
          ) : null}
          {error ? <div className="form-error">{error}</div> : null}
          <div className="ticket-form-foot">
            <span className="kbd-hint">Cmd/Ctrl + Enter to save · Esc to close</span>
            <span className="spacer" />
            <button type="button" className="button subtle" onClick={onClose}>Cancel</button>
            <Button type="submit" className="button primary" disabled={saving || !d.title.trim()}>{saving ? "Saving..." : initial.title ? "Save changes" : "Create note"}</Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function DetailDrawer({ note, onClose, onEdit, onTogglePin, onToggleDone, onArchive, onDelete, onDuplicate, onCopyRef, onCopyAgent, busy }: {
  note: Note;
  onClose: () => void;
  onEdit: () => void;
  onTogglePin: () => void;
  onToggleDone: () => void;
  onArchive: () => void;
  onDelete: () => void;
  onDuplicate: () => void;
  onCopyRef: () => void;
  onCopyAgent: () => void;
  busy: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const Icon = CATEGORY_ICON[note.category];
  const done = note.status === "done";
  return (
    <div className="ticket-drawer-backdrop" onMouseDown={onClose}>
      <aside className="ticket-drawer" role="dialog" aria-modal="true" aria-label={note.title} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ticket-drawer-head">
          <span className="ticket-cat" data-cat={note.category}><Icon size={12} /> {CATEGORY_LABEL[note.category]}</span>
          <span className="ticket-ref">{noteRef(note)}</span>
          <span className="ticket-status" data-status={note.status}><StatusDot value={note.status} /> {STATUS_LABEL[note.status]}</span>
          <span className="spacer" />
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close detail"><X size={17} /></button>
        </div>
        <h2 className="ticket-drawer-title">{note.title}</h2>
        <div className="ticket-drawer-meta">
          <span title={"Updated: " + fullDate(note.updated_at)}>Updated {relativeTime(note.updated_at)}</span>
          <span aria-hidden="true">·</span>
          <span title={"Created: " + fullDate(note.created_at)}>Created {relativeTime(note.created_at)}</span>
          {note.priority !== "none" ? (<span className="ticket-priority" data-p={note.priority}><Flag size={11} /> {note.priority}</span>) : null}
          {note.pinned ? <span className="ticket-pin on"><Pin size={12} /> Pinned</span> : null}
        </div>
        {(note.tags || []).length ? (
          <div className="ticket-drawer-tags">{(note.tags || []).map((t) => <span key={t} className="tag-chip static">{t}</span>)}</div>
        ) : null}
        <div className="ticket-drawer-body">
          {note.content ? <Markdown text={note.content} command={note.category === "command"} /> : <p className="muted">No description yet.</p>}
        </div>
        <dl className="ticket-kv">
          <div><dt>Repository</dt><dd>{note.repository || "Personal"}</dd></div>
          {note.branch ? <div><dt>Branch</dt><dd><code>{note.branch}</code></dd></div> : null}
          {note.file_path ? <div><dt>Path</dt><dd><code>{note.file_path}</code></dd></div> : null}
          {note.commit_hash ? <div><dt>Commit</dt><dd><code>{note.commit_hash.slice(0, 12)}</code></dd></div> : null}
          {note.related_url ? <div><dt>Link</dt><dd><a href={note.related_url} target="_blank" rel="noreferrer">{note.related_url}</a></dd></div> : null}
          {note.due_date ? <div><dt>Follow-up</dt><dd title={fullDate(note.due_date)}>{relativeTime(note.due_date)}</dd></div> : null}
          <div><dt>ID</dt><dd><code title={note.id}>{noteRef(note)}</code></dd></div>
        </dl>
        <div className="ticket-drawer-actions">
          <Button className="button primary" onClick={onEdit} disabled={busy}><Pencil size={14} /> Edit</Button>
          <button type="button" className="button subtle" onClick={onToggleDone} disabled={busy}><Check size={14} /> {done ? "Reopen" : "Done"}</button>
          <button type="button" className="button subtle" onClick={onTogglePin} disabled={busy}><Pin size={14} /> {note.pinned ? "Unpin" : "Pin"}</button>
          <button type="button" className="button subtle" onClick={onArchive} disabled={busy}><Archive size={14} /> {note.archived ? "Unarchive" : "Archive"}</button>
        </div>
        <div className="ticket-drawer-actions secondary">
          <button type="button" className="button subtle" onClick={onDuplicate} disabled={busy}><Copy size={14} /> Duplicate</button>
          <button type="button" className="button subtle" onClick={onCopyRef}><Copy size={14} /> Copy ref</button>
          <button type="button" className="button subtle" onClick={onCopyAgent}><Sparkles size={14} /> Agent ctx</button>
          <button type="button" className="button subtle danger-text" onClick={onDelete} disabled={busy}><Trash2 size={14} /> Delete</button>
        </div>
      </aside>
    </div>
  );
}

export function NotesView({ token, repos }: { token: string; repos: string[] }) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<NoteCategory | "all">("all");
  const [status, setStatus] = useState<NoteStatus | "all" | "active">("all");
  const [sort, setSort] = useState<SortKey>(() => (localStorage.getItem("updater-notes-sort") as SortKey) || "updated");
  const [groupBy, setGroupBy] = useState<GroupKey>(() => (localStorage.getItem("updater-notes-group") as GroupKey) || "none");
  const [datePreset, setDatePreset] = useState<DatePreset>("all");
  const [dateField, setDateField] = useState<DateField>("updated_at");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [tagFilter, setTagFilter] = useState("all");
  const [repoFilter, setRepoFilter] = useState("all");
  const [showArchived, setShowArchived] = useState(false);
  const [composerOpen, setComposerOpen] = useState(false);
  const [editing, setEditing] = useState<Note | null>(null);
  const [composerKey, setComposerKey] = useState(0);
  const [saving, setSaving] = useState(false);
  const [composerError, setComposerError] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => { localStorage.setItem("updater-notes-sort", sort); }, [sort]);
  useEffect(() => { localStorage.setItem("updater-notes-group", groupBy); }, [groupBy]);
  useEffect(() => { if (toast) { const t = window.setTimeout(() => setToast(""), 2200); return () => window.clearTimeout(t); } }, [toast]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api<Note[]>("/notes", token).then((items) => {
      if (cancelled) return;
      setNotes(items.map(normalizeNote));
      setError("");
    }).catch((err) => {
      if (cancelled) return;
      setError(err instanceof Error ? err.message : "Unable to load notes");
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [token]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
      if (e.key === "Escape") {
        if (menuId) setMenuId(null);
        else if (detailId && !composerOpen && !editing) setDetailId(null);
        return;
      }
      if (typing || composerOpen || editing) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "n" || e.key === "N") { e.preventDefault(); openComposer(null); }
      else if (e.key === "/") { e.preventDefault(); searchRef.current?.focus(); }
      else if ((e.key === "e" || e.key === "E") && selectedId) { const n = notes.find((x) => x.id === selectedId); if (n) openComposer(n); }
      else if ((e.key === "p" || e.key === "P") && selectedId) { const n = notes.find((x) => x.id === selectedId); if (n) togglePin(n); }
      else if ((e.key === "d" || e.key === "D") && selectedId) { const n = notes.find((x) => x.id === selectedId); if (n) toggleDone(n); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const allTags = useMemo(() => {
    const set = new Map<string, number>();
    notes.forEach((n) => (n.tags || []).forEach((t) => set.set(t, (set.get(t) || 0) + 1)));
    return Array.from(set.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map((e) => e[0]);
  }, [notes]);

  const allRepos = useMemo(() => {
    const set = new Map<string, number>();
    notes.forEach((n) => { if (n.repository) set.set(n.repository, (set.get(n.repository) || 0) + 1); });
    (repos || []).forEach((r) => {
      let short = r;
      try { short = new URL(r).pathname.replace(/\.git$/, "").replace(/^\//, "") || r; } catch { short = r; }
      if (!set.has(r) && !set.has(short)) set.set(r, 0);
    });
    return Array.from(set.keys()).sort();
  }, [notes, repos]);

  const openCount = notes.filter((n) => !n.archived && n.status !== "archived" && (n.status === "open" || n.status === "in-progress")).length;
  const allCount = notes.filter((n) => !n.archived && n.status !== "archived").length;
  const pinnedCount = notes.filter((n) => n.pinned && !n.archived && n.status !== "archived").length;

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    let list = notes.filter((n) => {
      const isArchived = n.archived || n.status === "archived";
      if (isArchived && !showArchived && status !== "archived") return false;
      if (category !== "all" && n.category !== category) return false;
      if (status === "active") { if (!(n.status === "open" || n.status === "in-progress") || isArchived) return false; }
      else if (status !== "all" && n.status !== status) return false;
      if (tagFilter !== "all" && (n.tags || []).indexOf(tagFilter) === -1) return false;
      if (repoFilter === "none") { if (n.repository) return false; }
      else if (repoFilter !== "all" && n.repository !== repoFilter) return false;
      const df: string | null = dateField === "created_at" ? n.created_at : dateField === "due_date" ? n.due_date : n.updated_at;
      if (!dateInPreset(df, datePreset, customFrom, customTo)) return false;
      if (q) {
        const hay = (n.title + " " + n.content + " " + (n.tags || []).join(" ") + " " + (n.repository || "") + " " + n.category + " " + n.status).toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });
    const by: Record<SortKey, (a: Note, b: Note) => number> = {
      updated: (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      created: (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      oldest: (a, b) => new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime(),
      priority: (a, b) => PRIORITY_ORDER[b.priority] - PRIORITY_ORDER[a.priority] || new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      category: (a, b) => a.category.localeCompare(b.category) || new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      title: (a, b) => a.title.localeCompare(b.title),
    };
    list = list.slice().sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
      return by[sort](a, b);
    });
    return list;
  }, [notes, search, category, status, tagFilter, repoFilter, datePreset, dateField, customFrom, customTo, sort, showArchived]);

  const grouped = useMemo(() => {
    if (groupBy === "none") return [{ key: "all", label: "", items: filtered }];
    const map = new Map<string, Note[]>();
    if (groupBy === "date") {
      const buckets = ["Pinned", "Today", "Yesterday", "Earlier this week", "Earlier this month", "Older"];
      buckets.forEach((b) => map.set(b, []));
      filtered.forEach((n) => {
        if (n.pinned) { map.get("Pinned")!.push(n); return; }
        const d = new Date(n.updated_at);
        const now = new Date();
        if (dayKey(d) === dayKey(now)) map.get("Today")!.push(n);
        else {
          const y = new Date(now); y.setDate(now.getDate() - 1);
          if (dayKey(d) === dayKey(y)) map.get("Yesterday")!.push(n);
          else if (Date.now() - d.getTime() <= 7 * 86400000) map.get("Earlier this week")!.push(n);
          else if (d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()) map.get("Earlier this month")!.push(n);
          else map.get("Older")!.push(n);
        }
      });
      return buckets.filter((b) => (map.get(b) || []).length).map((b) => ({ key: b, label: b, items: map.get(b)! }));
    }
    filtered.forEach((n) => {
      const k = groupBy === "category" ? CATEGORY_LABEL[n.category] : groupBy === "status" ? STATUS_LABEL[n.status] : (n.repository || "Personal");
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push(n);
    });
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0])).map((e) => ({ key: e[0], label: e[0], items: e[1] }));
  }, [filtered, groupBy]);

  const hasFilters = search.trim() !== "" || category !== "all" || status !== "all" || tagFilter !== "all" || repoFilter !== "all" || datePreset !== "all";
  const clearFilters = () => { setSearch(""); setCategory("all"); setStatus("all"); setTagFilter("all"); setRepoFilter("all"); setDatePreset("all"); setCustomFrom(""); setCustomTo(""); setShowArchived(false); };

  const openComposer = (n: Note | null) => { setEditing(n); setComposerError(""); setComposerKey((k) => k + 1); setComposerOpen(true); setMenuId(null); };

  const saveComposer = async (draft: ComposerDraft) => {
    if (!draft.title.trim() || saving) return;
    setSaving(true); setComposerError("");
    try {
      if (editing) {
        const payload = draftToPayload(draft);
        const updated = await api<Note>("/notes/" + editing.id, token, { method: "PATCH", body: JSON.stringify(payload) });
        const nn = normalizeNote(updated);
        setNotes((cur) => cur.map((x) => (x.id === editing.id ? nn : x)));
      } else {
        const payload = draftToPayload(draft);
        const created = await api<Note>("/notes", token, { method: "POST", body: JSON.stringify(payload) });
        const nn = normalizeNote(created);
        setNotes((cur) => [nn].concat(cur));
        setSelectedId(nn.id);
      }
      setComposerOpen(false); setEditing(null);
    } catch (err) { setComposerError(err instanceof Error ? err.message : "Unable to save note"); }
    finally { setSaving(false); }
  };

  const patchNote = async (n: Note, body: Record<string, unknown>) => {
    setBusyId(n.id); setError("");
    try {
      const updated = await api<Note>("/notes/" + n.id, token, { method: "PATCH", body: JSON.stringify(body) });
      const nn = normalizeNote(updated);
      setNotes((cur) => cur.map((x) => (x.id === n.id ? nn : x)));
      return nn;
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to update note"); return null; }
    finally { setBusyId(null); }
  };

  const togglePin = (n: Note) => { patchNote(n, { pinned: !n.pinned }); };
  const toggleDone = (n: Note) => {
    const next = n.status === "done" ? "open" : "done";
    patchNote(n, { status: next, archived: false });
  };
  const toggleArchive = (n: Note) => {
    const isA = n.archived || n.status === "archived";
    if (isA) patchNote(n, { archived: false, status: "open" });
    else patchNote(n, { archived: true, status: "archived" });
  };
  const removeNote = async (n: Note) => {
    if (!window.confirm("Delete note \"" + n.title + "\"? This cannot be undone.")) return;
    setBusyId(n.id); setError("");
    try {
      await api<{ ok: boolean }>("/notes/" + n.id, token, { method: "DELETE" });
      setNotes((cur) => cur.filter((x) => x.id !== n.id));
      if (detailId === n.id) setDetailId(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to delete note"); }
    finally { setBusyId(null); setMenuId(null); }
  };
  const duplicateNote = async (n: Note) => {
    setBusyId(n.id); setError("");
    try {
      const payload = { title: n.title + " (copy)", content: n.content, category: n.category, status: "open", priority: n.priority, tags: n.tags, repository: n.repository, branch: n.branch, file_path: n.file_path, commit_hash: n.commit_hash, related_url: n.related_url, color: n.color, pinned: false, archived: false };
      const created = await api<Note>("/notes", token, { method: "POST", body: JSON.stringify(payload) });
      const nn = normalizeNote(created);
      setNotes((cur) => [nn].concat(cur));
      setToast("Duplicated as " + noteRef(nn));
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to duplicate note"); }
    finally { setBusyId(null); setMenuId(null); }
  };

  const detailNote = detailId ? notes.find((x) => x.id === detailId) || null : null;
  const copyRef = (n: Note) => { copyText(noteRef(n)).then((ok) => setToast(ok ? "Copied " + noteRef(n) : "Copy failed")); setMenuId(null); };
  const copyAgent = (n: Note) => { copyText(agentContextText(n)).then((ok) => setToast(ok ? "Agent context copied" : "Copy failed")); setMenuId(null); };

  return (
    <div className="notes-page" onClick={() => setMenuId(null)}>
      <div className="notes-header">
        <div className="notes-title-block">
          <div className="feed-eyebrow"><span className="eyebrow-line" /> QUICK NOTES</div>
          <h2>Notes</h2>
          <p>Capture bugs, TODOs, implementation ideas, commands, and follow-ups while you work.</p>
          <div className="notes-stats">
            <span><strong>{allCount}</strong> All</span>
            <span aria-label="Open notes"><strong>{openCount}</strong> Open</span>
            <span><strong>{pinnedCount}</strong> Pinned</span>
          </div>
        </div>
        <div className="notes-header-actions">
          <Button className="button primary" onClick={() => openComposer(null)} aria-label="New note (N)"><Plus size={16} /> New note</Button>
        </div>
      </div>

      <div className="ticket-toolbar" role="search" aria-label="Search and filter notes">
        <label className="search-box ticket-search">
          <Search size={16} />
          <input ref={searchRef} placeholder="Search notes...  ( / )" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search notes" />
          {search ? <button type="button" className="clear-x" onClick={() => setSearch("")} aria-label="Clear search"><X size={14} /></button> : null}
        </label>
        <label className="ticket-select"><span className="sr">Type</span>
          <select value={category} onChange={(e) => setCategory(e.target.value as NoteCategory | "all")} aria-label="Filter by type">
            <option value="all">Type: All</option>
            {CATEGORY_ORDER.map((c) => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
          </select>
        </label>
        <label className="ticket-select"><span className="sr">Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value as NoteStatus | "all" | "active")} aria-label="Filter by status">
            <option value="all">Status: All</option>
            <option value="active">Active</option>
            <option value="open">Open</option>
            <option value="in-progress">In progress</option>
            <option value="done">Done</option>
            <option value="archived">Archived</option>
          </select>
        </label>
        <label className="ticket-select"><span className="sr">Date field</span>
          <select value={dateField} onChange={(e) => setDateField(e.target.value as DateField)} aria-label="Date field">
            <option value="updated_at">Updated</option>
            <option value="created_at">Created</option>
            <option value="due_date">Due</option>
          </select>
        </label>
        <label className="ticket-select"><span className="sr">Date</span>
          <select value={datePreset} onChange={(e) => setDatePreset(e.target.value as DatePreset)} aria-label="Filter by date">
            {DATE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        <label className="ticket-select"><span className="sr">Tag</span>
          <select value={tagFilter} onChange={(e) => setTagFilter(e.target.value)} aria-label="Filter by tag">
            <option value="all">Tags: All</option>
            {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="ticket-select"><span className="sr">Repository</span>
          <select value={repoFilter} onChange={(e) => setRepoFilter(e.target.value)} aria-label="Filter by repository">
            <option value="all">Repo: All</option>
            <option value="none">Personal</option>
            {allRepos.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label className="ticket-select"><span className="sr">Sort</span>
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort notes">
            {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        <label className="ticket-select"><span className="sr">Group</span>
          <select value={groupBy} onChange={(e) => setGroupBy(e.target.value as GroupKey)} aria-label="Group notes">
            <option value="none">No grouping</option>
            <option value="date">Group by date</option>
            <option value="category">Group by type</option>
            <option value="status">Group by status</option>
            <option value="repository">Group by repo</option>
          </select>
        </label>
        {hasFilters || showArchived ? <button type="button" className="button subtle clear-filters" onClick={clearFilters}>Clear filters</button> : null}
      </div>
      {datePreset === "custom" ? (
        <div className="custom-dates">
          <label>From <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} aria-label="Custom from date" /></label>
          <label>To <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} aria-label="Custom to date" /></label>
          <label className="arch-toggle"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show archived</label>
        </div>
      ) : (
        <div className="custom-dates slim">
          <label className="arch-toggle"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show archived</label>
        </div>
      )}

      {loading ? <div className="loading-list">Loading your notes...</div> : error && notes.length === 0 ? (
        <div className="list-error"><strong>Could not load notes</strong><p>{error}</p></div>
      ) : filtered.length ? (
        <div className="ticket-groups">
          {grouped.map((g) => (
            <section key={g.key} className="ticket-group">
              {g.label ? <h4 className="ticket-group-title">{g.label} <span>{g.items.length}</span></h4> : null}
              <div className="ticket-list">
                {g.items.map((n) => (
                  <TicketCard key={n.id} note={n} selected={selectedId === n.id}
                    onOpen={() => { setDetailId(n.id); setSelectedId(n.id); }}
                    onFilterCategory={() => setCategory(n.category)}
                    onFilterTag={(t) => setTagFilter(t)}
                    onTogglePin={() => togglePin(n)}
                    onToggleDone={() => toggleDone(n)}
                    onMenu={() => setMenuId(menuId === n.id ? null : n.id)}
                    menuOpen={menuId === n.id}
                    onEdit={() => openComposer(n)}
                    onDuplicate={() => duplicateNote(n)}
                    onArchive={() => toggleArchive(n)}
                    onDelete={() => removeNote(n)}
                    onCopyRef={() => copyRef(n)}
                    onCopyAgent={() => copyAgent(n)}
                    busy={busyId === n.id} />
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : notes.length === 0 ? (
        <div className="no-matches">
          <StickyNote size={26} />
          <h3>No notes yet</h3>
          <p>No notes yet. Capture your first bug, TODO, idea, or implementation note.</p>
          <Button className="button primary" onClick={() => openComposer(null)}><Plus size={15} /> New note</Button>
        </div>
      ) : (
        <div className="no-matches">
          <Search size={26} />
          <h3>No notes match these filters</h3>
          <p>No notes match these filters.</p>
          <button type="button" className="button subtle" onClick={clearFilters}>Clear filters</button>
        </div>
      )}
      {error && notes.length > 0 ? <div className="form-error">{error}</div> : null}
      {toast ? <div className="ticket-toast" role="status">{toast}</div> : null}
      <p className="kbd-foot">N new · / search · E edit · P pin · D done · arrows + Enter to open · Esc close</p>
      {composerOpen ? (
        <ComposerModal key={composerKey} initial={editing ? draftFromNote(editing) : EMPTY_DRAFT} repositories={allRepos} saving={saving} error={composerError} onClose={() => { setComposerOpen(false); setEditing(null); }} onSave={saveComposer} />
      ) : null}
      {detailNote && !composerOpen ? (
        <DetailDrawer note={detailNote} busy={busyId === detailNote.id} onClose={() => setDetailId(null)}
          onEdit={() => openComposer(detailNote)}
          onTogglePin={() => togglePin(detailNote)}
          onToggleDone={() => toggleDone(detailNote)}
          onArchive={() => toggleArchive(detailNote)}
          onDelete={() => removeNote(detailNote)}
          onDuplicate={() => duplicateNote(detailNote)}
          onCopyRef={() => copyRef(detailNote)}
          onCopyAgent={() => copyAgent(detailNote)} />
      ) : null}
    </div>
  );
}
