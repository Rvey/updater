import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  FolderKanban,
  LogOut,
  Mail,
  Plus,
  Trash2,
  Users,
} from "lucide-react";
import { createApi } from "./lib/api";
import type {
  Invite,
  Member,
  Workspace,
  WorkspaceProject,
  WorkspaceRole,
} from "./types";
import { Button } from "./components/ui/button";
import "./settings.css";
import "./workspaces.css";

export const INVITE_STORAGE_KEY = "updater-invite";
export const WORKSPACE_STORAGE_KEY = "updater-workspace";
export const PROJECT_STORAGE_KEY = "updater-project";

export function readStored(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string | null) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

export function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
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
      document.body.removeChild(field);
      return ok;
    } catch {
      return false;
    }
  }
}

export function WorkspaceSwitcher({
  workspaces,
  activeWorkspaceId,
  activeProjectId,
  notice,
  onSelectWorkspace,
  onSelectProject,
  onCreateWorkspace,
  onCreateProject,
  onOpenMembers,
}: {
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  activeProjectId: string | null;
  notice: string;
  onSelectWorkspace: (id: string) => void;
  onSelectProject: (id: string | null) => void;
  onCreateWorkspace: (name: string) => Promise<void>;
  onCreateProject: (name: string, repoUrl: string) => Promise<void>;
  onOpenMembers: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState<"workspace" | "project" | null>(null);
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const workspace =
    workspaces.find((item) => item.id === activeWorkspaceId) || workspaces[0];
  if (!workspace) return null;
  const project = workspace.projects.find((item) => item.id === activeProjectId);

  const close = () => {
    setCreating(null);
    setName("");
    setRepoUrl("");
    setError("");
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      if (creating === "workspace") await onCreateWorkspace(name.trim());
      else await onCreateProject(name.trim(), repoUrl.trim());
      close();
    } catch (err) {
      setError(errorText(err, "Could not create"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ws-switcher">
      <button
        className="ws-trigger"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="ws-trigger-text">
          <span className="ws-trigger-name">{workspace.name}</span>
          <span className="ws-trigger-sub">
            {project ? project.name : "All projects"}
          </span>
        </span>
        {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>
      {notice && <p className="ws-notice">{notice}</p>}
      {open && (
        <div className="ws-panel">
          {workspaces.length > 1 && (
            <>
              <div className="ws-heading">WORKSPACES</div>
              {workspaces.map((item) => (
                <button
                  key={item.id}
                  className={item.id === workspace.id ? "ws-item active" : "ws-item"}
                  onClick={() => onSelectWorkspace(item.id)}
                >
                  <span>{item.name}</span>
                  {item.id === workspace.id && <Check size={13} />}
                </button>
              ))}
            </>
          )}
          <div className="ws-heading">PROJECTS</div>
          <button
            className={!project ? "ws-item active" : "ws-item"}
            onClick={() => onSelectProject(null)}
          >
            <span>All projects</span>
            {!project && <Check size={13} />}
          </button>
          {workspace.projects.map((item: WorkspaceProject) => (
            <button
              key={item.id}
              className={item.id === project?.id ? "ws-item active" : "ws-item"}
              onClick={() => onSelectProject(item.id)}
            >
              <span>{item.name}</span>
              {item.id === project?.id && <Check size={13} />}
            </button>
          ))}
          {creating ? (
            <form className="ws-create" onSubmit={submit}>
              <input
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={creating === "workspace" ? "Workspace name" : "Project name"}
                maxLength={120}
              />
              {creating === "project" && (
                <input
                  value={repoUrl}
                  onChange={(event) => setRepoUrl(event.target.value)}
                  placeholder="Repo URL (optional)"
                />
              )}
              {error && <p className="ws-error">{error}</p>}
              <div className="ws-create-actions">
                <Button type="submit" className="button primary" disabled={busy || !name.trim()}>
                  Create
                </Button>
                <button type="button" className="ws-link" onClick={close}>
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <div className="ws-actions">
              <button className="ws-item" onClick={() => setCreating("project")}>
                <Plus size={13} /> New project
              </button>
              <button className="ws-item" onClick={() => setCreating("workspace")}>
                <Plus size={13} /> New workspace
              </button>
              <button
                className="ws-item"
                onClick={() => {
                  setOpen(false);
                  onOpenMembers();
                }}
              >
                <Users size={13} /> Members
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function MembersPage({
  token,
  workspace,
  email,
  onChanged,
  onLeft,
}: {
  token: string;
  workspace: Workspace;
  email: string | null;
  onChanged: () => void;
  onLeft: () => void;
}) {
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>("member");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ email: string; link: string } | null>(null);
  const [copied, setCopied] = useState("");
  const isOwner = workspace.role === "owner";
  const workspaceId = workspace.id;

  const load = useCallback(async () => {
    const api = createApi(token);
    try {
      const people = await api.get<Member[]>(`/workspaces/${workspaceId}/members`);
      setMembers(people);
      if (isOwner) {
        setInvites(await api.get<Invite[]>(`/workspaces/${workspaceId}/invites`));
      } else {
        setInvites([]);
      }
      setError("");
    } catch (err) {
      setError(errorText(err, "Unable to load members"));
    } finally {
      setLoading(false);
    }
  }, [token, workspaceId, isOwner]);

  useEffect(() => {
    setLoading(true);
    setCreated(null);
    load();
  }, [load]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(errorText(err, "Request failed"));
    } finally {
      setBusy(false);
    }
  };

  const inviteLink = (invite: Invite) =>
    `${window.location.origin}/app?invite=${invite.token}`;

  const copy = async (key: string, value: string) => {
    if (await copyText(value)) {
      setCopied(key);
      window.setTimeout(() => setCopied(""), 1800);
    }
  };

  const invite = (event: FormEvent) => {
    event.preventDefault();
    if (!inviteEmail.trim()) return;
    run(async () => {
      const api = createApi(token);
      // Existing accounts are added directly; unknown emails get an invite with a one-time token.
      const result = await api.post<Partial<Invite> & { email?: string }>(
        `/workspaces/${workspaceId}/members`,
        { email: inviteEmail.trim(), role: inviteRole },
      );
      if (result.token) {
        setCreated({ email: result.email || inviteEmail.trim(), link: inviteLink(result as Invite) });
      } else {
        setCreated(null);
      }
      setInviteEmail("");
      await load();
      onChanged();
    });
  };

  const changeRole = (member: Member, role: WorkspaceRole) =>
    run(async () => {
      await createApi(token).patch(`/workspaces/${workspaceId}/members/${member.user_id}`, { role });
      await load();
      onChanged();
    });

  const remove = (member: Member) => {
    const self = Boolean(email) && member.email.toLowerCase() === email!.toLowerCase();
    const text = self
      ? `Leave ${workspace.name}?`
      : `Remove ${member.email} from ${workspace.name}?`;
    if (!window.confirm(text)) return;
    run(async () => {
      await createApi(token).del(`/workspaces/${workspaceId}/members/${member.user_id}`);
      if (self) {
        onLeft();
      } else {
        await load();
        onChanged();
      }
    });
  };

  const revoke = (item: Invite) =>
    run(async () => {
      await createApi(token).del(`/workspaces/${workspaceId}/invites/${item.id}`);
      await load();
    });

  return (
    <div className="settings-page ws-page">
      <div className="ws-page-inner">
        <header className="ws-page-head">
          <h2>Members</h2>
          <p>
            People in <strong>{workspace.name}</strong> can see every project in it.
            {isOwner ? " Owners can invite people and change roles." : ""}
          </p>
        </header>
        {error && <p className="ws-error">{error}</p>}

        <section className="settings-card">
          <div className="settings-card-head">
            <div className="settings-card-icon">
              <Users size={17} />
            </div>
            <div>
              <h3>Workspace members</h3>
              <p>{members.length} {members.length === 1 ? "person" : "people"}</p>
            </div>
          </div>
          {loading ? (
            <p className="ws-muted">Loading members...</p>
          ) : (
            <ul className="ws-list">
              {members.map((member) => {
                const self = Boolean(email) && member.email.toLowerCase() === email!.toLowerCase();
                return (
                  <li key={member.user_id}>
                    <span className="ws-person">
                      <span className="ws-avatar">{member.email.slice(0, 1).toUpperCase()}</span>
                      <span>
                        {member.email}
                        {self && <em> (you)</em>}
                      </span>
                    </span>
                    <span className="ws-row-actions">
                      {isOwner ? (
                        <select
                          value={member.role}
                          disabled={busy}
                          aria-label={`Role for ${member.email}`}
                          onChange={(event) => changeRole(member, event.target.value as WorkspaceRole)}
                        >
                          <option value="owner">Owner</option>
                          <option value="member">Member</option>
                        </select>
                      ) : (
                        <span className={`ws-badge ${member.role}`}>{member.role}</span>
                      )}
                      {(isOwner || self) && (
                        <button
                          className="ws-icon-btn"
                          disabled={busy}
                          onClick={() => remove(member)}
                          title={self ? "Leave workspace" : "Remove member"}
                          aria-label={self ? "Leave workspace" : `Remove ${member.email}`}
                        >
                          {self ? <LogOut size={14} /> : <Trash2 size={14} />}
                        </button>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {isOwner && (
          <section className="settings-card">
            <div className="settings-card-head">
              <div className="settings-card-icon">
                <Mail size={17} />
              </div>
              <div>
                <h3>Invite someone</h3>
                <p>
                  Existing accounts are added straight away. Otherwise you get a link to
                  send them yourself; no email is sent.
                </p>
              </div>
            </div>
            <form className="ws-invite-form" onSubmit={invite}>
              <input
                type="email"
                required
                value={inviteEmail}
                onChange={(event) => setInviteEmail(event.target.value)}
                placeholder="teammate@example.com"
              />
              <select
                value={inviteRole}
                onChange={(event) => setInviteRole(event.target.value as WorkspaceRole)}
                aria-label="Role"
              >
                <option value="member">Member</option>
                <option value="owner">Owner</option>
              </select>
              <Button type="submit" className="button primary" disabled={busy || !inviteEmail.trim()}>
                Invite
              </Button>
            </form>
            {created && (
              <div className="ws-link-box">
                <p>
                  Invite link for <strong>{created.email}</strong>. It is shown once.
                </p>
                <div className="ws-link-row">
                  <code>{created.link}</code>
                  <button className="ws-link" onClick={() => copy("new", created.link)}>
                    {copied === "new" ? <Check size={13} /> : <Copy size={13} />}
                    {copied === "new" ? "Copied" : "Copy link"}
                  </button>
                </div>
              </div>
            )}
            {invites.length > 0 && (
              <>
                <div className="ws-heading ws-sub">PENDING INVITES</div>
                <ul className="ws-list">
                  {invites.map((item) => (
                    <li key={item.id}>
                      <span className="ws-person">
                        <span className="ws-avatar">{item.email.slice(0, 1).toUpperCase()}</span>
                        <span>
                          {item.email}
                          <em> expires {new Date(item.expires_at).toLocaleDateString()}</em>
                        </span>
                      </span>
                      <span className="ws-row-actions">
                        <span className={`ws-badge ${item.role}`}>{item.role}</span>
                        <button
                          className="ws-icon-btn"
                          disabled={busy}
                          onClick={() => revoke(item)}
                          title="Revoke invite"
                          aria-label={`Revoke invite for ${item.email}`}
                        >
                          <Trash2 size={14} />
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        )}

        <section className="settings-card">
          <div className="settings-card-head">
            <div className="settings-card-icon">
              <FolderKanban size={17} />
            </div>
            <div>
              <h3>Projects</h3>
              <p>Tasks, notes, tech debt and updates belong to one project.</p>
            </div>
          </div>
          <ul className="ws-list">
            {workspace.projects.map((item) => (
              <li key={item.id}>
                <span className="ws-person">
                  <span>
                    {item.name}
                    {item.repo_url && <em> {item.repo_url}</em>}
                  </span>
                </span>
                {item.is_default && <span className="ws-badge member">default</span>}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
