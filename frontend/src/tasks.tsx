import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  CalendarClock,
  Check,
  CircleCheck,
  CircleDot,
  CircleDashed,
  Github,
  Inbox,
  Loader2,
  Pencil,
  Plus,
  Search,
  Sparkles,
  SquareKanban,
  Trash2,
  X,
} from "lucide-react";
import type {
  NewTask,
  Task,
  TaskPriority,
  TaskStatus,
  TaskUpdate,
} from "./types";
import { Button } from "./components/ui/button";
import {
  Kanban,
  KanbanBoard,
  KanbanColumn,
  KanbanColumnContent,
  KanbanItem,
  KanbanItemHandle,
  KanbanOverlay,
  type KanbanCommitMeta,
} from "./components/ui/kanban";
import "./tasks.css";

const apiBase = (import.meta as any).env.VITE_API_BASE_URL || "";

async function api<T>(
  path: string,
  token: string,
  options?: RequestInit,
): Promise<T> {
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
    const error = new Error(
      body.detail || "Request failed (" + response.status + ")",
    ) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return response.json() as Promise<T>;
}

const STATUS_ORDER: TaskStatus[] = ["backlog", "in-progress", "review", "done"];

const STATUS_META: Record<
  TaskStatus,
  { label: string; hint: string; icon: typeof CircleDashed }
> = {
  backlog: {
    label: "Backlog",
    hint: "Scoped, not started",
    icon: CircleDashed,
  },
  "in-progress": {
    label: "In Progress",
    hint: "Being worked on",
    icon: CircleDot,
  },
  review: { label: "Review", hint: "Needs a look", icon: Search },
  done: { label: "Done", hint: "Shipped or closed", icon: CircleCheck },
};

const PRIORITY_ORDER: TaskPriority[] = ["low", "medium", "high"];
const PRIORITY_LABEL: Record<TaskPriority, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

function repoShort(url: string) {
  try {
    const parts = new URL(url).pathname
      .replace(/\.git$/, "")
      .split("/")
      .filter(Boolean);
    if (parts.length >= 2)
      return parts[parts.length - 2] + "/" + parts[parts.length - 1];
    return parts[parts.length - 1] || url;
  } catch {
    return url;
  }
}

function dateLabel(date: string) {
  try {
    return new Date(date).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
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

function dueLabel(date: string) {
  const due = new Date(date);
  const dayStart = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((dayStart(due) - dayStart(new Date())) / 86400000);
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  if (days === -1) return "Due yesterday";
  if (days < 0) return Math.abs(days) + "d overdue";
  if (days < 7) return "Due in " + days + "d";
  return (
    "Due " + due.toLocaleDateString("en-US", { month: "short", day: "numeric" })
  );
}

function isOverdue(task: Task) {
  if (!task.due_date || task.status === "done") return false;
  const due = new Date(task.due_date);
  const endOfDay = new Date(
    due.getFullYear(),
    due.getMonth(),
    due.getDate(),
    23,
    59,
    59,
  ).getTime();
  return endOfDay < Date.now();
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

function emptyColumns(): Record<TaskStatus, Task[]> {
  return { backlog: [], "in-progress": [], review: [], done: [] };
}

function groupTasks(tasks: Task[]): Record<TaskStatus, Task[]> {
  const columns = emptyColumns();
  for (const task of tasks) {
    const status = STATUS_ORDER.includes(task.status) ? task.status : "backlog";
    columns[status].push(task);
  }
  for (const status of STATUS_ORDER) {
    columns[status].sort(
      (a, b) =>
        a.position - b.position || a.created_at.localeCompare(b.created_at),
    );
  }
  return columns;
}

function flattenColumns(columns: Record<string, Task[]>): Task[] {
  const flat: Task[] = [];
  for (const status of STATUS_ORDER) {
    (columns[status] ?? []).forEach((task, index) => {
      flat.push({ ...task, status, position: index });
    });
  }
  return flat;
}

function toDateInput(value: string | null) {
  if (!value) return "";
  try {
    return new Date(value).toISOString().slice(0, 10);
  } catch {
    return "";
  }
}

function PriorityBadge({ priority }: { priority: TaskPriority }) {
  return (
    <span className="tk-priority" data-p={priority}>
      {PRIORITY_LABEL[priority] ?? priority}
    </span>
  );
}

function StatusPill({ status }: { status: TaskStatus }) {
  const meta = STATUS_META[status] ?? STATUS_META.backlog;
  const Icon = meta.icon;
  return (
    <span className="tk-status" data-status={status}>
      <Icon size={12} /> {meta.label.toUpperCase()}
    </span>
  );
}

function TaskCard({
  task,
  isOverlay,
  onOpen,
}: {
  task: Task;
  isOverlay?: boolean;
  onOpen?: () => void;
}) {
  const overdue = isOverdue(task);
  const card = (
    <article
      className={"tk-card" + (isOverlay ? " is-overlay" : "")}
      data-priority={task.priority}
      onClick={onOpen}
    >
      <div className="tk-card-top">
        <PriorityBadge priority={task.priority} />
        {task.repo_url && (
          <span className="tk-card-repo" title={task.repo_url}>
            <Github size={11} /> {repoShort(task.repo_url)}
          </span>
        )}
      </div>
      <h4 className="tk-card-title">{task.title}</h4>
      {task.description && <p className="tk-card-desc">{task.description}</p>}
      {task.tags.length > 0 && (
        <div className="tk-card-tags">
          {task.tags.slice(0, 3).map((tag) => (
            <span className="tk-chip" key={tag}>
              #{tag}
            </span>
          ))}
          {task.tags.length > 3 && (
            <span className="tk-chip more">+{task.tags.length - 3}</span>
          )}
        </div>
      )}
      <div className="tk-card-foot">
        {task.due_date ? (
          <span className={"tk-due" + (overdue ? " is-overdue" : "")}>
            <CalendarClock size={12} /> {dueLabel(task.due_date)}
          </span>
        ) : (
          <span className="tk-card-hint">
            {task.branch ? task.branch : "No due date"}
          </span>
        )}
        {task.assignee && (
          <span className="tk-avatar" title={task.assignee}>
            {initials(task.assignee)}
          </span>
        )}
      </div>
    </article>
  );

  if (isOverlay) return card;

  return (
    <KanbanItem
      value={task.id}
      className="tk-item"
      onKeyDown={(e) => {
        if (onOpen && e.key === "Enter" && e.target === e.currentTarget)
          onOpen();
      }}
    >
      <KanbanItemHandle className="tk-handle">{card}</KanbanItemHandle>
    </KanbanItem>
  );
}

function TaskColumn({
  status,
  tasks,
  onOpen,
  onAdd,
}: {
  status: TaskStatus;
  tasks: Task[];
  onOpen: (task: Task) => void;
  onAdd: (status: TaskStatus) => void;
}) {
  const meta = STATUS_META[status];
  return (
    <KanbanColumn value={status} className="tk-col" data-status={status}>
      <header className="tk-col-head">
        <span className="tk-col-dot" />
        <div className="tk-col-titles">
          <h3>{meta.label}</h3>
          <span>{meta.hint}</span>
        </div>
        <span className="tk-col-count">{tasks.length}</span>
        <button
          type="button"
          className="tk-col-add"
          onClick={() => onAdd(status)}
          aria-label={"Add task to " + meta.label}
          title={"Add task to " + meta.label}
        >
          <Plus size={14} />
        </button>
      </header>
      <KanbanColumnContent value={status} className="tk-col-body">
        {tasks.map((task) => (
          <TaskCard key={task.id} task={task} onOpen={() => onOpen(task)} />
        ))}
        {tasks.length === 0 && (
          <div className="tk-col-empty">
            <span>Drop a task here</span>
          </div>
        )}
      </KanbanColumnContent>
    </KanbanColumn>
  );
}

type ModalState =
  { mode: "create"; status: TaskStatus } | { mode: "edit"; task: Task } | null;

function TaskModal({
  close,
  save,
  saving,
  repos,
  state,
}: {
  close: () => void;
  save: (value: NewTask | TaskUpdate) => Promise<void>;
  saving: boolean;
  repos: string[];
  state: Exclude<ModalState, null>;
}) {
  const editing = state.mode === "edit" ? state.task : null;
  const [form, setForm] = useState(() => ({
    title: editing?.title ?? "",
    description: editing?.description ?? "",
    status: (editing?.status ??
      (state.mode === "create" ? state.status : "backlog")) as TaskStatus,
    priority: (editing?.priority ?? "medium") as TaskPriority,
    repo_url: editing?.repo_url ?? "",
    branch: editing?.branch ?? "",
    assignee: editing?.assignee ?? "",
    due_date: toDateInput(editing?.due_date ?? null),
    tags: (editing?.tags ?? []).join(", "),
  }));
  const [error, setError] = useState("");
  const set = (key: keyof typeof form, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      await save({
        title: form.title.trim(),
        description: form.description.trim(),
        status: form.status,
        priority: form.priority,
        repo_url: form.repo_url.trim() || null,
        branch: form.branch.trim() || null,
        assignee: form.assignee.trim() || null,
        due_date: form.due_date
          ? new Date(form.due_date + "T12:00:00").toISOString()
          : null,
        tags: form.tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save task");
    }
  };

  return (
    <div className="tk-modal-backdrop" onMouseDown={close}>
      <div
        className="tk-modal"
        role="dialog"
        aria-modal="true"
        aria-label={editing ? "Edit task" : "New task"}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="tk-modal-head">
          <div>
            <div className="tk-eyebrow">
              {editing ? "EDIT TASK" : "NEW TASK"}
            </div>
            <h3>{editing ? "Update the task" : "Add a task to the board"}</h3>
          </div>
          <button
            type="button"
            className="tk-icon-btn"
            onClick={close}
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
        <form className="tk-form" onSubmit={onSubmit}>
          <label className="tk-field">
            <span>Title</span>
            <input
              required
              autoFocus
              value={form.title}
              placeholder="e.g. Wire drag-and-drop persistence"
              onChange={(e) => set("title", e.target.value)}
            />
          </label>
          <label className="tk-field">
            <span>
              Description <em>optional</em>
            </span>
            <textarea
              rows={4}
              value={form.description}
              placeholder="What needs to happen, and what does done look like?"
              onChange={(e) => set("description", e.target.value)}
            />
          </label>
          <div className="tk-grid-3">
            <label className="tk-field">
              <span>Status</span>
              <select
                value={form.status}
                onChange={(e) => set("status", e.target.value)}
              >
                {STATUS_ORDER.map((status) => (
                  <option key={status} value={status}>
                    {STATUS_META[status].label}
                  </option>
                ))}
              </select>
            </label>
            <label className="tk-field">
              <span>Priority</span>
              <select
                value={form.priority}
                onChange={(e) => set("priority", e.target.value)}
              >
                {PRIORITY_ORDER.map((priority) => (
                  <option key={priority} value={priority}>
                    {PRIORITY_LABEL[priority]}
                  </option>
                ))}
              </select>
            </label>
            <label className="tk-field">
              <span>
                Due date <em>optional</em>
              </span>
              <input
                type="date"
                value={form.due_date}
                onChange={(e) => set("due_date", e.target.value)}
              />
            </label>
          </div>
          <div className="tk-grid-2">
            <label className="tk-field">
              <span>
                Repository <em>optional</em>
              </span>
              <input
                list="tk-repo-options"
                value={form.repo_url}
                placeholder="https://github.com/you/project"
                onChange={(e) => set("repo_url", e.target.value)}
              />
            </label>
            <label className="tk-field">
              <span>
                Branch <em>optional</em>
              </span>
              <input
                value={form.branch}
                placeholder="rvey/task-board"
                onChange={(e) => set("branch", e.target.value)}
              />
            </label>
          </div>
          <div className="tk-grid-2">
            <label className="tk-field">
              <span>
                Assignee <em>optional</em>
              </span>
              <input
                value={form.assignee}
                placeholder="Who owns this?"
                onChange={(e) => set("assignee", e.target.value)}
              />
            </label>
            <label className="tk-field">
              <span>
                Tags <em>comma separated</em>
              </span>
              <input
                value={form.tags}
                placeholder="frontend, board"
                onChange={(e) => set("tags", e.target.value)}
              />
            </label>
          </div>
          <datalist id="tk-repo-options">
            {repos.map((repo) => (
              <option key={repo} value={repo} />
            ))}
          </datalist>
          {error && <div className="tk-form-error">{error}</div>}
          <div className="tk-form-foot">
            <button type="button" className="tk-btn" onClick={close}>
              Cancel
            </button>
            <Button type="submit" className="button primary" disabled={saving}>
              {saving ? "Saving…" : editing ? "Save task" : "Create task"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function TaskDetail({
  task,
  busy,
  onMove,
  onEdit,
  onDelete,
  onClose,
}: {
  task: Task;
  busy: string;
  onMove: (status: TaskStatus) => void;
  onEdit: () => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const overdue = isOverdue(task);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="tk-drawer-backdrop" onMouseDown={onClose}>
      <aside
        className="tk-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Task details"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="tk-drawer-head">
          <StatusPill status={task.status} />
          <PriorityBadge priority={task.priority} />
          <span className="spacer" />
          <button
            type="button"
            className="tk-icon-btn"
            onClick={onClose}
            aria-label="Close task"
          >
            <X size={16} />
          </button>
        </div>
        <h2 className="tk-drawer-title">{task.title}</h2>
        <div className="tk-drawer-meta">
          <span>Created {relativeDate(task.created_at)}</span>
          <span>·</span>
          <span>Updated {relativeDate(task.updated_at)}</span>
          {task.completed_at && (
            <>
              <span>·</span>
              <span className="tk-done-date">
                <Check size={12} /> Done {dateLabel(task.completed_at)}
              </span>
            </>
          )}
        </div>
        <div className="tk-drawer-tags">
          {task.repo_url && (
            <a
              className="tk-chip link"
              href={task.repo_url}
              target="_blank"
              rel="noreferrer"
            >
              <Github size={11} /> {repoShort(task.repo_url)}
            </a>
          )}
          {task.branch && <span className="tk-chip">⌥ {task.branch}</span>}
          {task.due_date && (
            <span className={"tk-chip" + (overdue ? " danger" : "")}>
              <CalendarClock size={11} /> {dueLabel(task.due_date)}
            </span>
          )}
          {task.assignee && (
            <span className="tk-chip">
              <span className="tk-avatar tiny">{initials(task.assignee)}</span>{" "}
              {task.assignee}
            </span>
          )}
        </div>

        <section className="tk-section">
          <h3>Description</h3>
          {task.description ? (
            <p className="tk-section-body">{task.description}</p>
          ) : (
            <p className="tk-muted">
              No description yet — edit the task to add one.
            </p>
          )}
        </section>

        {task.tags.length > 0 && (
          <section className="tk-section">
            <h3>Tags</h3>
            <div className="tk-drawer-tags">
              {task.tags.map((tag) => (
                <span className="tk-chip" key={tag}>
                  #{tag}
                </span>
              ))}
            </div>
          </section>
        )}

        <section className="tk-section">
          <h3>Move to</h3>
          <div className="tk-status-grid">
            {STATUS_ORDER.map((status) => {
              const meta = STATUS_META[status];
              const Icon = meta.icon;
              return (
                <button
                  type="button"
                  key={status}
                  className={
                    "tk-status-btn" +
                    (task.status === status ? " is-active" : "")
                  }
                  disabled={busy !== "" || task.status === status}
                  onClick={() => onMove(status)}
                >
                  <Icon size={14} /> {meta.label}
                </button>
              );
            })}
          </div>
        </section>

        <section className="tk-section">
          <h3>Details</h3>
          <dl className="tk-kv">
            <div>
              <dt>Task ID</dt>
              <dd>
                <code>{task.id}</code>
              </dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{STATUS_META[task.status]?.label ?? task.status}</dd>
            </div>
            <div>
              <dt>Priority</dt>
              <dd>{PRIORITY_LABEL[task.priority] ?? task.priority}</dd>
            </div>
            <div>
              <dt>Repository</dt>
              <dd>
                {task.repo_url ? (
                  <a href={task.repo_url} target="_blank" rel="noreferrer">
                    {task.repo_url}
                  </a>
                ) : (
                  <span className="tk-muted">—</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Branch</dt>
              <dd>
                {task.branch ? (
                  <code>{task.branch}</code>
                ) : (
                  <span className="tk-muted">—</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Assignee</dt>
              <dd>{task.assignee ?? <span className="tk-muted">—</span>}</dd>
            </div>
            <div>
              <dt>Due</dt>
              <dd>
                {task.due_date ? (
                  fullDateTime(task.due_date)
                ) : (
                  <span className="tk-muted">—</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{fullDateTime(task.created_at)}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{fullDateTime(task.updated_at)}</dd>
            </div>
            <div>
              <dt>Completed</dt>
              <dd>
                {task.completed_at ? (
                  fullDateTime(task.completed_at)
                ) : (
                  <span className="tk-muted">—</span>
                )}
              </dd>
            </div>
            {task.author_agent && (
              <div>
                <dt>Author agent</dt>
                <dd>
                  <Sparkles size={12} /> {task.author_agent}
                </dd>
              </div>
            )}
          </dl>
        </section>

        <div className="tk-drawer-actions">
          <button
            type="button"
            className="tk-btn"
            onClick={onEdit}
            disabled={busy !== ""}
          >
            <Pencil size={14} /> Edit task
          </button>
          <button
            type="button"
            className="tk-btn danger"
            onClick={onDelete}
            disabled={busy !== ""}
          >
            {busy === "delete" ? (
              <Loader2 size={14} className="spin" />
            ) : (
              <Trash2 size={14} />
            )}
            Delete
          </button>
        </div>
      </aside>
    </div>
  );
}

export function TasksView({
  token,
  repos,
}: {
  token: string;
  repos: string[];
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [repoFilter, setRepoFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState("");
  const [savingBoard, setSavingBoard] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const load = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await api<Task[]>("/tasks", token);
      setTasks(data);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load tasks");
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const repoOptions = useMemo(
    () =>
      Array.from(
        new Set([
          ...repos,
          ...tasks
            .map((task) => task.repo_url)
            .filter((url): url is string => Boolean(url)),
        ]),
      ),
    [repos, tasks],
  );

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return tasks.filter((task) => {
      if (repoFilter !== "all" && task.repo_url !== repoFilter) return false;
      if (priorityFilter !== "all" && task.priority !== priorityFilter)
        return false;
      if (!q) return true;
      return (
        task.title +
        " " +
        task.description +
        " " +
        (task.assignee ?? "") +
        " " +
        (task.branch ?? "") +
        " " +
        task.tags.join(" ")
      )
        .toLowerCase()
        .includes(q);
    });
  }, [tasks, search, repoFilter, priorityFilter]);

  const columns = useMemo(() => groupTasks(filtered), [filtered]);
  const selected = tasks.find((task) => task.id === selectedId) || null;

  const applyColumns = (next: Record<string, Task[]>) => {
    setTasks(flattenColumns(next));
  };

  const persistColumns = async (
    next: Record<string, Task[]>,
    meta: KanbanCommitMeta<Task>,
  ) => {
    setSavingBoard(true);
    try {
      const payload = {
        columns: Object.fromEntries(
          STATUS_ORDER.map((status) => [
            status,
            (next[status] ?? []).map((task) => task.id),
          ]),
        ),
      };
      const updated = await api<Task[]>("/tasks/reorder", token, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setTasks(updated);
      const moved = updated.find(
        (task) => task.id === String(meta.event.active.id),
      );
      if (moved && moved.status !== meta.activeContainer) {
        setToast("Moved to " + STATUS_META[moved.status].label);
      }
    } catch (err) {
      applyColumns(meta.previousValue);
      setToast(err instanceof Error ? err.message : "Could not save the board");
    } finally {
      setSavingBoard(false);
    }
  };

  const create = async (value: NewTask | TaskUpdate) => {
    setSaving(true);
    try {
      const created = await api<Task>("/tasks", token, {
        method: "POST",
        body: JSON.stringify(value),
      });
      setTasks((current) => [...current, created]);
      setSelectedId(created.id);
      setModal(null);
      setToast("Task created");
    } finally {
      setSaving(false);
    }
  };

  const update = async (task: Task, value: NewTask | TaskUpdate) => {
    setSaving(true);
    try {
      const updated = await api<Task>("/tasks/" + task.id, token, {
        method: "PATCH",
        body: JSON.stringify(value),
      });
      setTasks((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setModal(null);
      setToast("Task saved");
      if (value.status && value.status !== task.status) await load(true);
    } finally {
      setSaving(false);
    }
  };

  const changeStatus = async (task: Task, status: TaskStatus) => {
    if (status === task.status) return;
    setBusy(status);
    try {
      const updated = await api<Task>("/tasks/" + task.id, token, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setTasks((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setToast("Moved to " + STATUS_META[status].label);
      await load(true);
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Unable to move task");
    } finally {
      setBusy("");
    }
  };

  const remove = async (task: Task) => {
    if (!window.confirm("Delete this task?")) return;
    setBusy("delete");
    try {
      await api<{ ok: boolean }>("/tasks/" + task.id, token, {
        method: "DELETE",
      });
      setTasks((current) => current.filter((item) => item.id !== task.id));
      setSelectedId(null);
      setToast("Task deleted");
      await load(true);
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Unable to delete task");
    } finally {
      setBusy("");
    }
  };

  const openCount = tasks.filter(
    (task) => task.status === "backlog" || task.status === "in-progress",
  ).length;
  const progressCount = tasks.filter(
    (task) => task.status === "in-progress",
  ).length;
  const reviewCount = tasks.filter((task) => task.status === "review").length;
  const doneCount = tasks.filter((task) => task.status === "done").length;
  const overdueCount = tasks.filter(isOverdue).length;

  const hasFilters =
    search.trim() !== "" || repoFilter !== "all" || priorityFilter !== "all";

  return (
    <div className="tk-page">
      <header className="tk-head">
        <div className="tk-title-block">
          <div className="tk-eyebrow">
            <span className="tk-eyebrow-line" /> TASK BOARD
          </div>
          <h2>Tasks</h2>
          <p>
            Plan the work around your ship log. Drag a card to change its status
            — every move is saved to the board.
          </p>
          {savingBoard && (
            <div className="tk-saving">
              <Loader2 size={12} className="spin" /> Saving board…
            </div>
          )}
        </div>
        <div className="tk-head-actions">
          <Button
            className="button primary"
            onClick={() => setModal({ mode: "create", status: "backlog" })}
          >
            <Plus size={15} /> New task
          </Button>
        </div>
      </header>

      <div className="tk-stats">
        <div className="tk-stat">
          <strong>{String(openCount).padStart(2, "0")}</strong>
          <span>OPEN</span>
        </div>
        <div className="tk-stat progress">
          <strong>{String(progressCount).padStart(2, "0")}</strong>
          <span>IN PROGRESS</span>
        </div>
        <div className="tk-stat review">
          <strong>{String(reviewCount).padStart(2, "0")}</strong>
          <span>IN REVIEW</span>
        </div>
        <div className="tk-stat done">
          <strong>{String(doneCount).padStart(2, "0")}</strong>
          <span>DONE</span>
        </div>
        {overdueCount > 0 && (
          <div className="tk-stat overdue">
            <strong>{String(overdueCount).padStart(2, "0")}</strong>
            <span>OVERDUE</span>
          </div>
        )}
      </div>

      <div className="tk-toolbar">
        <label className="tk-search">
          <Search size={15} />
          <input
            placeholder="Search tasks, tags, branches…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search tasks"
          />
          {search && (
            <button
              type="button"
              className="tk-search-clear"
              onClick={() => setSearch("")}
              aria-label="Clear search"
            >
              <X size={13} />
            </button>
          )}
        </label>
        <select
          value={repoFilter}
          onChange={(e) => setRepoFilter(e.target.value)}
          aria-label="Filter by repository"
        >
          <option value="all">All repos</option>
          {repoOptions.map((repo) => (
            <option key={repo} value={repo}>
              {repoShort(repo)}
            </option>
          ))}
        </select>
        <select
          value={priorityFilter}
          onChange={(e) => setPriorityFilter(e.target.value)}
          aria-label="Filter by priority"
        >
          <option value="all">Any priority</option>
          {PRIORITY_ORDER.map((priority) => (
            <option key={priority} value={priority}>
              {PRIORITY_LABEL[priority]}
            </option>
          ))}
        </select>
        {hasFilters && (
          <button
            type="button"
            className="tk-clear-filters"
            onClick={() => {
              setSearch("");
              setRepoFilter("all");
              setPriorityFilter("all");
            }}
          >
            Clear filters
          </button>
        )}
        <span className="tk-count">{filtered.length} TASKS</span>
      </div>

      {loading ? (
        <div className="tk-state">
          <Loader2 size={20} className="spin" />
          <span>Loading your task board…</span>
        </div>
      ) : error ? (
        <div className="tk-state">
          <Inbox size={22} />
          <h3>Could not load tasks</h3>
          <p>{error}</p>
          <button type="button" className="tk-btn" onClick={() => load()}>
            Try again
          </button>
        </div>
      ) : tasks.length === 0 ? (
        <div className="tk-state">
          <SquareKanban size={26} />
          <h3>Your board is empty</h3>
          <p>
            Add the first task — plan the work, then drag it across the board as
            it moves.
          </p>
          <Button
            className="button primary"
            onClick={() => setModal({ mode: "create", status: "backlog" })}
          >
            <Plus size={15} /> Add your first task
          </Button>
        </div>
      ) : (
        <div className="tk-board-wrap">
          <Kanban
            value={columns}
            onValueChange={applyColumns}
            getItemValue={(task) => task.id}
            onValueCommit={persistColumns}
          >
            <KanbanBoard className="tk-board">
              {STATUS_ORDER.map((status) => (
                <TaskColumn
                  key={status}
                  status={status}
                  tasks={columns[status]}
                  onOpen={(task) => setSelectedId(task.id)}
                  onAdd={(target) =>
                    setModal({ mode: "create", status: target })
                  }
                />
              ))}
            </KanbanBoard>
            <KanbanOverlay className="tk-overlay">
              {({ value, variant }) => {
                if (variant !== "item") return null;
                const task = tasks.find((item) => item.id === value);
                return task ? <TaskCard task={task} isOverlay /> : null;
              }}
            </KanbanOverlay>
          </Kanban>
        </div>
      )}

      {selected && (
        <TaskDetail
          key={selected.id}
          task={selected}
          busy={busy}
          onMove={(status) => changeStatus(selected, status)}
          onEdit={() => setModal({ mode: "edit", task: selected })}
          onDelete={() => remove(selected)}
          onClose={() => setSelectedId(null)}
        />
      )}

      {modal && (
        <TaskModal
          close={() => setModal(null)}
          saving={saving}
          repos={repoOptions}
          state={modal}
          save={(value) =>
            modal.mode === "edit" ? update(modal.task, value) : create(value)
          }
        />
      )}

      {toast && <div className="tk-toast">{toast}</div>}
    </div>
  );
}
