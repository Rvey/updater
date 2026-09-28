import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Bot,
  Check,
  CircleAlert,
  Copy,
  KeyRound,
  LockKeyhole,
  Mail,
  RefreshCw,
  ShieldCheck,
  Terminal,
  UserRound,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Update } from "./types";
import { Button } from "./components/ui/button";
import "./settings.css";

const apiBase = import.meta.env.VITE_API_BASE_URL || "";

async function api<T>(
  path: string,
  token: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(apiBase + "/api" + path, {
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

function shellQuote(value: string) {
  return "'" + value.replace(/'/g, "'\\''") + "'";
}

function shortDate(value: string) {
  try {
    return new Date(value).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return value;
  }
}

export type SettingsSection = "keys" | "account" | "agents";

type ApiKeyInfo = {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

const SECTIONS: {
  id: SettingsSection;
  label: string;
  hint: string;
  icon: LucideIcon;
}[] = [
  { id: "keys", label: "API keys", hint: "Credentials for your agents", icon: KeyRound },
  { id: "account", label: "Account", hint: "Email and password", icon: UserRound },
  { id: "agents", label: "Connected agents", hint: "MCP setup for each agent", icon: Bot },
];

function CopyChip({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <button
      type="button"
      className="settings-copy"
      aria-label={"Copy " + label}
      title={"Copy " + label}
      onClick={() => {
        setFailed(false);
        copyText(value).then((ok) => {
          if (!ok) {
            setFailed(true);
            return;
          }
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1600);
        });
      }}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {copied ? "Copied" : failed ? "Copy blocked" : "Copy"}
    </button>
  );
}

function CardHead({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <div className="settings-card-head">
      <div className="settings-card-icon">
        <Icon size={18} />
      </div>
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
    </div>
  );
}

function ApiKeysSection({
  token,
  canManage,
  onConnect,
}: {
  token: string;
  canManage: boolean;
  onConnect: () => void;
}) {
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [name, setName] = useState("agent key");
  const [created, setCreated] = useState<{ name: string; key: string } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(canManage);
  const [busy, setBusy] = useState(false);
  const [revoking, setRevoking] = useState("");

  useEffect(() => {
    if (!canManage) return;
    let cancelled = false;
    setLoading(true);
    api<ApiKeyInfo[]>("/auth/keys", token)
      .then((items) => {
        if (!cancelled) {
          setKeys(items);
          setError("");
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, canManage]);

  const create = (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    api<{ id: string; name: string; key: string }>("/auth/keys", token, {
      method: "POST",
      body: JSON.stringify({ name: name.trim() || "agent key" }),
    })
      .then((item) => {
        setCreated({ name: item.name, key: item.key });
        setName("agent key");
        return api<ApiKeyInfo[]>("/auth/keys", token);
      })
      .then(setKeys)
      .catch((err) => setError(err.message))
      .finally(() => setBusy(false));
  };

  const revoke = (id: string) => {
    setRevoking(id);
    setError("");
    api<{ ok: boolean }>(`/auth/keys/${id}`, token, { method: "DELETE" })
      .then(() => {
        setKeys((current) =>
          current.map((item) =>
            item.id === id ? { ...item, revoked_at: new Date().toISOString() } : item,
          ),
        );
      })
      .catch((err) => setError(err.message))
      .finally(() => setRevoking(""));
  };

  const activeCount = keys.filter((item) => !item.revoked_at).length;

  return (
    <section className="settings-card" aria-labelledby="settings-keys-title">
      <CardHead
        icon={KeyRound}
        title="API keys"
        description="Keys sign in your coding agents over MCP and HTTP. Treat a key like a password: keep it in an env var, never in git."
      />
      {!canManage ? (
        <div className="settings-note">
          <ShieldCheck size={16} />
          <span>
            You are signed in with a server token. Sign in with your email and password
            to create and revoke per-agent keys here.
          </span>
        </div>
      ) : (
        <>
          <div className="settings-row-meta">
            <span>
              {keys.length} key{keys.length === 1 ? "" : "s"} · {activeCount} active
            </span>
            <button type="button" className="settings-link" onClick={onConnect}>
              <Terminal size={13} /> Set up a new agent
            </button>
          </div>
          {created && (
            <div className="settings-created">
              <div className="settings-created-head">
                <strong>{created.name}</strong>
                <span>Copy it now — the full key is shown only once.</span>
              </div>
              <div className="code-block">
                <CopyChip value={created.key} label="API key" />
                <pre>{created.key}</pre>
              </div>
            </div>
          )}
          <form className="settings-inline-form" onSubmit={create}>
            <label className="settings-field">
              <span>New key name</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={80}
                placeholder="e.g. opencode · my-laptop"
              />
            </label>
            <Button type="submit" className="button primary" disabled={busy}>
              {busy ? "Creating…" : "Create key"}
            </Button>
          </form>

          <div className="settings-key-list">
            {loading ? (
              <p className="settings-hint">Loading keys…</p>
            ) : keys.length ? (
              keys.map((item) => (
                <div className={"settings-key-row" + (item.revoked_at ? " revoked" : "")} key={item.id}>
                  <span className="settings-key-dot" aria-hidden="true" />
                  <div className="settings-key-main">
                    <strong>{item.name}</strong>
                    <span className="settings-key-prefix">{item.prefix}…</span>
                  </div>
                  <div className="settings-key-meta">
                    <span>
                      {item.last_used_at ? "Last used " + shortDate(item.last_used_at) : "Never used"}
                    </span>
                    <span>Created {shortDate(item.created_at)}</span>
                  </div>
                  {item.revoked_at ? (
                    <span className="settings-key-badge revoked">REVOKED</span>
                  ) : (
                    <button
                      type="button"
                      className="settings-key-revoke"
                      onClick={() => revoke(item.id)}
                      disabled={revoking === item.id}
                    >
                      {revoking === item.id ? "Revoking…" : "Revoke"}
                    </button>
                  )}
                </div>
              ))
            ) : (
              <p className="settings-hint">No keys yet. Create one to connect an agent.</p>
            )}
          </div>
        </>
      )}
      {error && (
        <div className="settings-feedback error">
          <CircleAlert size={14} /> {error}
        </div>
      )}
    </section>
  );
}

function AccountSection({
  token,
  email,
  onEmailChange,
}: {
  token: string;
  email: string | null;
  onEmailChange: (email: string) => void;
}) {
  const [emailDraft, setEmailDraft] = useState(email || "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    setEmailDraft(email || "");
  }, [email]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    const nextEmail = emailDraft.trim().toLowerCase();
    const emailChanged = Boolean(email) && nextEmail !== email;
    if (!currentPassword) {
      setError("Enter your current password to save changes.");
      return;
    }
    if (newPassword && newPassword.length < 8) {
      setError("New password must be at least 8 characters.");
      return;
    }
    if (newPassword && newPassword !== confirmPassword) {
      setError("New password and confirmation do not match.");
      return;
    }
    if (newPassword && newPassword === currentPassword) {
      setError("New password must be different from your current password.");
      return;
    }
    if (!emailChanged && !newPassword) {
      setError("Change your email or enter a new password first.");
      return;
    }
    setBusy(true);
    api<{
      email: string;
      email_changed: boolean;
      password_changed: boolean;
      sessions_revoked: number;
    }>("/auth/account", token, {
      method: "PATCH",
      body: JSON.stringify({
        current_password: currentPassword,
        ...(emailChanged ? { email: nextEmail } : {}),
        ...(newPassword ? { new_password: newPassword } : {}),
      }),
    })
      .then((res) => {
        onEmailChange(res.email);
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        const parts: string[] = [];
        if (res.email_changed) parts.push("Email updated");
        if (res.password_changed) parts.push("Password changed");
        let message = parts.join(" · ") || "Nothing changed";
        if (res.sessions_revoked > 0) {
          message += ` — ${res.sessions_revoked} other session${res.sessions_revoked === 1 ? "" : "s"} signed out`;
        }
        setSuccess(message + ".");
      })
      .catch((err) => setError(err.message))
      .finally(() => setBusy(false));
  };

  return (
    <section className="settings-card" aria-labelledby="settings-account-title">
      <CardHead
        icon={UserRound}
        title="Account"
        description="Your sign-in email and password. Changing the password signs out every other device; this session stays signed in."
      />
      {!email ? (
        <div className="settings-note">
          <ShieldCheck size={16} />
          <span>
            You are signed in with a server token. Sign in with an account to manage
            your email and password here.
          </span>
        </div>
      ) : (
        <form onSubmit={submit}>
          <div className="settings-form-grid">
            <label className="settings-field full">
              <span>
                <Mail size={13} /> Email
              </span>
              <input
                type="email"
                value={emailDraft}
                onChange={(e) => setEmailDraft(e.target.value)}
                autoComplete="email"
                maxLength={320}
                spellCheck={false}
              />
            </label>
            <label className="settings-field">
              <span>
                <LockKeyhole size={13} /> Current password
              </span>
              <input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="Required to save changes"
              />
            </label>
            <label className="settings-field">
              <span>
                <KeyRound size={13} /> New password
              </span>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
                placeholder="Leave blank to keep current"
              />
            </label>
            <label className="settings-field full">
              <span>Confirm new password</span>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
                placeholder="Repeat the new password"
                disabled={!newPassword}
              />
            </label>
          </div>
          <div className="settings-actions">
            <Button type="submit" className="button primary" disabled={busy}>
              {busy ? "Saving…" : "Save changes"}
            </Button>
            <span className="settings-hint">Minimum 8 characters for a new password.</span>
          </div>
          {success && (
            <div className="settings-feedback ok">
              <Check size={14} /> {success}
            </div>
          )}
          {error && (
            <div className="settings-feedback error">
              <CircleAlert size={14} /> {error}
            </div>
          )}
        </form>
      )}
    </section>
  );
}

function ConnectedAgentsSection({ token, updates }: { token: string; updates: Update[] }) {
  const [tab, setTab] = useState<"opencode" | "codex" | "claude">("opencode");
  const [copiedId, setCopiedId] = useState("");
  const [copyError, setCopyError] = useState(false);
  const [includeToken, setIncludeToken] = useState(false);
  const defaultOrigin =
    apiBase ||
    (window.location.port === "5173"
      ? `${window.location.protocol}//${window.location.hostname}:8000`
      : window.location.origin);
  const [mcpUrl, setMcpUrl] = useState(new URL("/mcp", defaultOrigin).href);

  const embed = includeToken && token.length > 0;
  const oneStep = {
    opencode: `curl -fsSL ${new URL("/connect.sh", defaultOrigin).href} | bash -s -- --url ${mcpUrl} --agents opencode${embed ? ` --token ${shellQuote(token)}` : ""}`,
    codex: `curl -fsSL ${new URL("/connect.sh", defaultOrigin).href} | bash -s -- --url ${mcpUrl} --agents codex${embed ? ` --token ${shellQuote(token)}` : ""}`,
    claude: `curl -fsSL ${new URL("/connect.sh", defaultOrigin).href} | bash -s -- --url ${mcpUrl} --agents claude${embed ? ` --token ${shellQuote(token)}` : ""}`,
  };
  const manual = {
    opencode: `opencode mcp add updater --global --url ${mcpUrl}${embed ? ` --header ${shellQuote("Authorization=Bearer " + token)}` : ' --header "Authorization=Bearer {env:UPDATER_TOKEN}"'}`,
    codex: `codex mcp add updater --url ${mcpUrl}${embed ? ` --bearer-token ${shellQuote(token)}` : " --bearer-token-env-var UPDATER_TOKEN"}`,
    claude: `claude mcp add --transport http --scope user updater ${mcpUrl}${embed ? ` --header ${shellQuote("Authorization: Bearer " + token)}` : ' --header "Authorization: Bearer $UPDATER_TOKEN"'}`,
  };
  const verify = {
    opencode: "opencode mcp list",
    codex: "codex mcp list",
    claude: "claude mcp list",
  };
  const agentLabel = { opencode: "OpenCode", codex: "Codex", claude: "Claude Code" };

  const connected = useMemo(() => {
    const map = new Map<string, { count: number; last: string }>();
    for (const item of updates) {
      const agent = (item.author_agent || "").trim();
      if (!agent) continue;
      const current = map.get(agent);
      if (!current) {
        map.set(agent, { count: 1, last: item.shipped_at });
      } else {
        map.set(agent, {
          count: current.count + 1,
          last: item.shipped_at > current.last ? item.shipped_at : current.last,
        });
      }
    }
    return [...map.entries()]
      .map(([agent, stats]) => ({ agent, ...stats }))
      .sort((a, b) => b.count - a.count);
  }, [updates]);

  const copy = (id: string, value: string) => {
    setCopyError(false);
    copyText(value).then((ok) => {
      if (!ok) {
        setCopyError(true);
        return;
      }
      setCopiedId(id);
      window.setTimeout(() => setCopiedId(""), 1800);
    });
  };

  return (
    <section className="settings-card" aria-labelledby="settings-agents-title">
      <CardHead
        icon={Bot}
        title="Connected agents"
        description="Run one command in your terminal and the agent can publish and read updates through Updater over MCP."
      />
      <label className="settings-field full">
        <span>MCP server URL</span>
        <div className="settings-url-row">
          <input
            type="url"
            value={mcpUrl}
            onChange={(e) => setMcpUrl(e.target.value)}
            spellCheck={false}
          />
          <CopyChip value={mcpUrl} label="MCP URL" />
        </div>
      </label>
      <div className="setup-tabs settings-tabs">
        {(["opencode", "codex", "claude"] as const).map((item) => (
          <button
            key={item}
            type="button"
            className={tab === item ? "active" : ""}
            onClick={() => setTab(item)}
          >
            {agentLabel[item]}
          </button>
        ))}
      </div>
      <label className="setup-check">
        <input
          type="checkbox"
          checked={includeToken}
          onChange={(e) => setIncludeToken(e.target.checked)}
        />
        Insert my current token directly (copy-paste ready)
      </label>
      {embed ? (
        <p className="setup-token-note">
          The command below contains your secret token. Anyone with it can access your
          workspace, and it will be saved in shell history. Untick the box for the safer
          env-var version.
        </p>
      ) : (
        <p className="setup-token-note">
          The command reads <code>UPDATER_TOKEN</code> from your environment. Set it in
          the terminal before running the command and launching the agent.
        </p>
      )}
      <p className="setup-verify">
        One-step (recommended): MCP + <code>/updater</code>, <code>/updater-ship</code>,{" "}
        <code>/updater-check</code>, <code>/updater-impact</code>, <code>/tech-depth</code>
      </p>
      <div className="code-block">
        <button
          type="button"
          aria-label="Copy one-step command"
          onClick={() => copy("onestep", oneStep[tab])}
        >
          {copiedId === "onestep" ? <Check size={15} /> : <Copy size={15} />}{" "}
          {copiedId === "onestep" ? "Copied" : "Copy"}
        </button>
        <pre>{oneStep[tab]}</pre>
      </div>
      <p className="setup-verify">Manual (MCP only):</p>
      <div className="code-block">
        <button
          type="button"
          aria-label="Copy MCP command"
          onClick={() => copy("manual", manual[tab])}
        >
          {copiedId === "manual" ? <Check size={15} /> : <Copy size={15} />}{" "}
          {copiedId === "manual" ? "Copied" : "Copy"}
        </button>
        <pre>{manual[tab]}</pre>
      </div>
      {copyError && (
        <p className="settings-feedback error">
          <CircleAlert size={14} /> Copy was blocked by the browser. Select the command to copy it.
        </p>
      )}
      <p className="setup-verify">
        Check connection: <code>{verify[tab]}</code>
      </p>

      <div className="settings-subhead">
        <h4>Agents that shipped here</h4>
        <span>Recorded from the agent name on each update.</span>
      </div>
      {connected.length ? (
        <div className="settings-agent-list">
          {connected.map((item) => (
            <div className="settings-agent-row" key={item.agent}>
              <span className="settings-agent-avatar">
                {item.agent.slice(0, 2).toUpperCase()}
              </span>
              <div className="settings-agent-main">
                <strong>{item.agent}</strong>
                <span>
                  {item.count} update{item.count === 1 ? "" : "s"} · last shipped {shortDate(item.last)}
                </span>
              </div>
              <span className="settings-agent-badge">CONNECTED</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="settings-note">
          <RefreshCw size={16} />
          <span>
            No agent has published yet. Run the one-step command above, then ship
            something — it will show up here.
          </span>
        </div>
      )}
    </section>
  );
}

export function SettingsView({
  token,
  email,
  updates,
  section,
  onSectionChange,
  onEmailChange,
}: {
  token: string;
  email: string | null;
  updates: Update[];
  section: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  onEmailChange: (email: string) => void;
}) {
  return (
    <div className="settings-page">
      <div className="settings-header">
        <div className="feed-eyebrow">
          <span className="eyebrow-line" /> WORKSPACE SETTINGS
        </div>
        <h2>Settings</h2>
        <p>Manage your account, API keys, and the agents connected to this workspace.</p>
      </div>
      <div className="settings-layout">
        <nav className="settings-rail" aria-label="Settings sections">
          {SECTIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={section === item.id ? "active" : ""}
              aria-current={section === item.id ? "page" : undefined}
              onClick={() => onSectionChange(item.id)}
            >
              <item.icon size={16} />
              <span>
                <strong>{item.label}</strong>
                <small>{item.hint}</small>
              </span>
            </button>
          ))}
        </nav>
        <div className="settings-content">
          {section === "keys" && (
            <ApiKeysSection
              token={token}
              canManage={Boolean(email)}
              onConnect={() => onSectionChange("agents")}
            />
          )}
          {section === "account" && (
            <AccountSection token={token} email={email} onEmailChange={onEmailChange} />
          )}
          {section === "agents" && <ConnectedAgentsSection token={token} updates={updates} />}
        </div>
      </div>
    </div>
  );
}
