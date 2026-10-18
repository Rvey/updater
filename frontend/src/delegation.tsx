import { type FormEvent, useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Bot, GitPullRequest, Loader2, X } from "lucide-react";
import { ApiError, request as api } from "./lib/api";
import type { Delegation, DelegationStatus, Task } from "./types";
import "./tasks.css";
import "./delegation.css";

const POLL_MS = 10_000;

export function isActive(status: DelegationStatus | undefined): boolean {
  return status === "queued" || status === "running";
}

/** A task can be delegated when it is tied to a GitHub repo. */
export function canDelegateTask(task: Pick<Task, "external_id" | "repo_url">): boolean {
  return (
    !!task.external_id?.startsWith("github:") ||
    /(^|\/\/|@)(www\.)?github\.com[/:]/i.test(task.repo_url ?? "")
  );
}

export function delegationErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.detail === "affinebot_not_linked")
      return "Affinebot isn't linked to this workspace. Link it in Settings > Integrations first.";
    if (err.detail === "affinebot_unreachable" || err.status === 502 || err.status === 504)
      return "Couldn't reach Affinebot right now. Try again in a moment.";
    if (err.detail === "updater_public_url_not_configured")
      return "The updater's public URL isn't configured, so Affinebot can't report back. Ask an admin to set it.";
    if (err.status === 422 && /repo/i.test(err.detail)) return "This task has no GitHub repo to delegate.";
    return err.detail;
  }
  return err instanceof Error ? err.message : "Something went wrong";
}

/* Tiny shared store so the card, drawer and GitHub row show the same state. */
const latest = new Map<string, Delegation | null>();
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const prListeners = new Set<(taskId: string) => void>();
/** Called once per task when its latest delegation moves from queued|running to pr_opened. */
export function onPrOpened(listener: (taskId: string) => void) {
  prListeners.add(listener);
  return () => void prListeners.delete(listener);
}
function setLatest(taskId: string, d: Delegation | null) {
  const prev = latest.get(taskId);
  latest.set(taskId, d);
  emit();
  if (d?.status === "pr_opened" && isActive(prev?.status)) prListeners.forEach((l) => l(taskId));
}
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => void listeners.delete(l);
};

/**
 * Latest delegation for a task. Fetches once when `enabled` (cards pass visibility),
 * then polls GET /delegations/{id} every 10s only while queued|running.
 */
export function useLatestDelegation(
  token: string,
  taskId: string,
  enabled = true,
) {
  const d = useSyncExternalStore(subscribe, () => latest.get(taskId));
  const loaded = d !== undefined;

  useEffect(() => {
    if (!enabled || loaded) return;
    let dead = false;
    api<Delegation[]>(`/tasks/${taskId}/delegations`, token)
      .then((list) => {
        if (!dead && !latest.has(taskId)) setLatest(taskId, list[0] ?? null);
      })
      .catch(() => {});
    return () => {
      dead = true;
    };
  }, [token, taskId, enabled, loaded]);

  const id = d?.id;
  const active = isActive(d?.status);
  useEffect(() => {
    if (!id || !active) return;
    let dead = false;
    const timer = window.setInterval(async () => {
      try {
        const next = await api<Delegation>(`/delegations/${id}`, token);
        if (dead) return;
        setLatest(taskId, next);
      } catch {
        /* keep polling; transient */
      }
    }, POLL_MS);
    return () => {
      dead = true;
      window.clearInterval(timer);
    };
  }, [token, taskId, id, active]);

  return d ?? null;
}

export function useDelegationActions(token: string, taskId: string) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const delegate = useCallback(
    async (body: { instruction?: string; base_branch?: string }) => {
      setBusy(true);
      setError("");
      try {
        const created = await api<Delegation>(`/tasks/${taskId}/delegate`, token, {
          method: "POST",
          body: JSON.stringify(body),
        });
        setLatest(taskId, created);
        return true;
      } catch (err) {
        setError(delegationErrorMessage(err));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [token, taskId],
  );
  const cancel = useCallback(
    async (id: string) => {
      setBusy(true);
      setError("");
      try {
        setLatest(taskId, await api<Delegation>(`/delegations/${id}/cancel`, token, { method: "POST" }));
      } catch (err) {
        setError(delegationErrorMessage(err));
      } finally {
        setBusy(false);
      }
    },
    [token, taskId],
  );
  return { delegate, cancel, busy, error, setError };
}

export function DelegationBadge({ delegation }: { delegation: Delegation | null }) {
  if (!delegation) return null;
  const { status } = delegation;
  if (status === "pr_opened" && delegation.pr_url) {
    return (
      <a
        className="dg-badge pr"
        href={delegation.pr_url}
        target="_blank"
        rel="noreferrer"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <GitPullRequest size={11} /> PR{delegation.pr_number ? ` #${delegation.pr_number}` : ""}
      </a>
    );
  }
  const label: Record<DelegationStatus, string> = {
    queued: "Queued",
    running: "Claude is working",
    pr_opened: "PR opened",
    failed: "Failed",
    cancelled: "Cancelled",
  };
  return (
    <span className={"dg-badge " + status} title={status === "failed" ? delegation.error ?? "Delegation failed" : undefined}>
      {status === "running" ? <span className="dg-dot" aria-hidden /> : <Bot size={11} />} {label[status]}
    </span>
  );
}

export function DelegateDialog({
  busy,
  error,
  onSubmit,
  onClose,
}: {
  busy: boolean;
  error: string;
  onSubmit: (body: { instruction?: string; base_branch?: string }) => void;
  onClose: () => void;
}) {
  const [instruction, setInstruction] = useState("");
  const [base, setBase] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({
      ...(instruction.trim() ? { instruction: instruction.trim() } : {}),
      ...(base.trim() ? { base_branch: base.trim() } : {}),
    });
  };
  return (
    <div className="tk-modal-backdrop dg-backdrop" onMouseDown={onClose}>
      <div
        className="tk-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Delegate to Claude Code"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            onClose();
          }
        }}
      >
        <div className="tk-modal-head">
          <div>
            <div className="tk-eyebrow">CLAUDE CODE</div>
            <h3>Delegate to Claude Code</h3>
          </div>
          <button type="button" className="tk-icon-btn" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <form className="tk-form" onSubmit={submit}>
          <label className="tk-field">
            <span>
              Instruction <em>optional</em>
            </span>
            <textarea
              rows={4}
              autoFocus
              value={instruction}
              placeholder="Anything Claude should know beyond the task description"
              onChange={(e) => setInstruction(e.target.value)}
            />
          </label>
          <label className="tk-field">
            <span>
              Base branch <em>optional, defaults to the repo's default</em>
            </span>
            <input value={base} placeholder="main" onChange={(e) => setBase(e.target.value)} />
          </label>
          {error && (
            <div className="tk-form-error" role="alert">
              {error}
            </div>
          )}
          <div className="tk-form-foot">
            <button type="button" className="tk-btn" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="tk-btn dg-primary" disabled={busy}>
              {busy ? <Loader2 size={13} className="spin" /> : <Bot size={13} />} Delegate
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** Button + dialog + badge + cancel/retry, self-contained for the drawer and GitHub rows. */
export function DelegateControl({
  token,
  taskId,
  compact,
}: {
  token: string;
  taskId: string;
  compact?: boolean;
}) {
  const d = useLatestDelegation(token, taskId, true);
  const { delegate, cancel, busy, error, setError } = useDelegationActions(token, taskId);
  const [open, setOpen] = useState(false);
  const active = isActive(d?.status);
  const retry = d?.status === "failed" || d?.status === "cancelled";
  return (
    <div className={"dg-control" + (compact ? " compact" : "")}>
      <DelegationBadge delegation={d} />
      {active ? (
        <button type="button" className="tk-btn" disabled={busy} onClick={() => d && cancel(d.id)}>
          Cancel
        </button>
      ) : (
        <button
          type="button"
          className="tk-btn"
          onClick={() => {
            setError("");
            setOpen(true);
          }}
        >
          <Bot size={13} /> {retry ? "Retry with Claude Code" : "Delegate to Claude Code"}
        </button>
      )}
      {!open && error && (
        <span className="dg-error" role="alert">
          {error}
        </span>
      )}
      {open && (
        <DelegateDialog
          busy={busy}
          error={error}
          onClose={() => setOpen(false)}
          onSubmit={async (body) => {
            if (await delegate(body)) setOpen(false);
          }}
        />
      )}
    </div>
  );
}

/** Card badge: fetched lazily once the card scrolls into view (no N+1 on load). */
export function CardDelegationBadge({ token, task }: { token: string; task: Task }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(false);
  const eligible = canDelegateTask(task);
  useEffect(() => {
    const el = ref.current;
    if (!eligible || !el) return;
    if (typeof IntersectionObserver === "undefined") return setVisible(true);
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setVisible(true);
        io.disconnect();
      }
    });
    io.observe(el);
    return () => io.disconnect();
  }, [eligible]);
  const d = useLatestDelegation(token, task.id, eligible && visible);
  return (
    <span ref={ref} className="dg-card-slot">
      <DelegationBadge delegation={d} />
    </span>
  );
}
