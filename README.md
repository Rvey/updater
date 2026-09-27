<p align="center">
  <img src="frontend/public/icon.svg" alt="Updater icon" width="96" />
</p>

# Updater — your shipping memory

[![License: MIT](https://img.shields.io/badge/License-MIT-lime.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](backend/pyproject.toml)
[![Node 20.19+](https://img.shields.io/badge/node-20.19%2B-green.svg)](frontend/package.json)
[![MCP](https://img.shields.io/badge/MCP-Streamable%20HTTP-purple.svg)](docs/agent-instructions.md)

Updater is an open-source shipping log for work done with coding agents. When an agent finishes and verifies a feature, it calls an MCP tool that saves the **what, why, how, expected impact, tradeoffs, files, and repo link**. The React workspace lets you search history, record what actually happened over time, and ask questions inside each update.

> Screenshots below are the real app running locally with demo content.

## Screenshots

### The real thing — workspace, ship log, and update detail

![Updater workspace showing the ship log with three updates and the update detail pane](docs/screenshots/app-overview.png)

The left column is the searchable ship log. The right pane is the selected update: why it was built, how it works, expected impact, files, tags, branch, and commit.

### Work in action — update detail

![Update detail view with why, how it works, impact, tradeoffs, files, and Q&A](docs/screenshots/update-detail.png)

Each update keeps its context together: reason, implementation notes, learning notes, files changed, dated impact observations, and a question thread.

### Work in action — instant search

![Typing mcp in search filters the ship log to matching updates](docs/screenshots/search-in-action.png)

Search filters as you type across titles, summaries, code paths, tags, and repos. Try `mcp`, `search`, or a repo name.

### Work in action — connect an agent in one command

![Connect an agent dialog with copyable MCP commands for OpenCode, Codex, and Claude Code](docs/screenshots/connect-agent.png)

Run one CLI command and your agent can publish and read updates through MCP. No manual MCP JSON editing.

## Features

- **Ship log UI** — browse, search, and filter every verified feature.
- **Update detail** — why, how it works, impact, tradeoffs, learning notes, files, tags, branch, commit, PR.
- **Impact over time** — add dated observations when you learn what a feature actually changed.
- **Q&A per update** — ask questions inside the update; answers stay attached to the decision.
- **Manual add** — capture an update from the UI when no agent was involved.
- **MCP server** — `publish_feature`, `list_feature_updates`, `get_feature_update`, `add_feature_impact` over Streamable HTTP at `/mcp` (stdio fallback included).
- **Auth** — log in with email + password and issue per-agent API keys (`upk_…`), or keep the single `UPDATER_TOKEN` env secret. Either unlocks the API + MCP.
- **Postgres in prod, SQLite locally** — zero-config local preview, persistent deployment with `DATABASE_URL`.
- **Dokploy-ready** — separate `web` + `api` services in `compose.dokploy.yml`.

## Stack

- Frontend: Vite 7 + React 19 + TypeScript + Tailwind CSS 4 + shadcn/ui (`base-rhea`, zinc, lime primary, Inter/Geist)
- Backend: FastAPI + SQLAlchemy 2 + Pydantic Settings
- DB: PostgreSQL via `DATABASE_URL` in prod; SQLite fallback (`backend/updater.db`) locally
- MCP: `mcp>=1.0,<2` over Streamable HTTP at `/mcp`, plus `python -m app.mcp_server` over stdio
- Optional AI answers: OpenRouter (`OPENROUTER_API_KEY`, `LLM_MODEL`) with saved-context fallback

The UI theme and Button component were generated from the requested shadcn preset. The [agent-skills project](https://github.com/addyosmani/agent-skills) informed the verify-then-ship workflow; it is not an app dependency.

## Quickstart

Requirements: Node.js 20.19+ or 22.12+, Python 3.11+, and [uv](https://docs.astral.sh/uv/).

```bash
# 1. API (terminal 1)
cd backend
uv sync --extra test
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 2. Web (terminal 2)
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Without a `.env` file the API creates `backend/updater.db` for local preview. API docs: <http://127.0.0.1:8000/docs>. Health: <http://127.0.0.1:8000/api/health>.

## Connect an agent

Start the API, then run **one** of these. Replace the URL with your deployed API HTTPS `/mcp` URL when connecting from another machine.

```bash
opencode mcp add updater --global --url http://127.0.0.1:8000/mcp
codex mcp add updater --url http://127.0.0.1:8000/mcp
claude mcp add --transport http --scope user updater http://127.0.0.1:8000/mcp
```

Verify with `opencode mcp list`, `codex mcp list`, or `claude mcp list`. The in-app **Connect an agent** dialog builds the same commands for any URL.
Want `/updater-ship`, `/updater-check`, `/updater-impact` too? `mcp add` cannot register slash commands, so use the one-step installer (MCP + commands). The dialog shows it per agent, or run:

```bash
curl -fsSL http://127.0.0.1:8000/connect.sh | bash -s -- --url http://127.0.0.1:8000/mcp --agents all
```
Run it bare for the interactive version — it asks for the token, then lets you pick any of opencode / codex / claude / cursor (one or many), then does the whole setup:

```bash
curl -fsSL http://127.0.0.1:8000/connect.sh | bash
```

If `UPDATER_TOKEN` is set on the API, export it where you launch the agent and use the secured variant:

```bash
export UPDATER_TOKEN='your-long-random-secret'
opencode mcp add updater --global --url http://127.0.0.1:8000/mcp --header 'Authorization=Bearer {env:UPDATER_TOKEN}'
codex mcp add updater --url http://127.0.0.1:8000/mcp --bearer-token-env-var UPDATER_TOKEN
claude mcp add --transport http --scope user updater http://127.0.0.1:8000/mcp --header "Authorization: Bearer $UPDATER_TOKEN"
```

OpenCode resolves `{env:UPDATER_TOKEN}` at runtime; Codex reads the named env var. Claude Code saves the expanded header into its user MCP settings — protect that file like a credential.

Prefer per-agent credentials: sign in to the web UI, open **API keys** in the sidebar, and create a key per agent. A key (`upk_…`) works anywhere the token does — `Authorization: Bearer upk_…` — and can be revoked individually without touching other agents.

Then copy the short rule in [docs/agent-instructions.md](docs/agent-instructions.md) into each target repo `AGENTS.md` / `CLAUDE.md` so the agent calls `publish_feature` **after shipped work is verified**. Use a stable `external_id` like `owner/repo:commit-sha:feature-slug`; retries return the same update.

Stdio fallback (local subprocess transport): `cd backend && uv run python -m app.mcp_server` with `UPDATER_API_URL` + `UPDATER_TOKEN` set.
If `POST /mcp` answers `421 Invalid Host header`, the fix is server-side: set `MCP_ALLOWED_HOSTS` to the public API hostname (see Configuration) and redeploy the API — reloading or re-adding the MCP client cannot fix a `421`.

## What gets saved

Title, summary, repo URL, reason, implementation explanation, expected impact, optional tradeoffs + learning notes, files changed, tags, agent name, branch, commit, PR link, shipping date. Dated impact notes and question threads stay attached to the update. You can also add updates manually from the UI.

## Configuration

Create `backend/.env` from `backend/.env.example`:

```dotenv
DATABASE_URL=postgresql://user:password@host:5432/updater?sslmode=require
UPDATER_TOKEN=your-long-random-secret
ALLOW_OPEN_REGISTRATION=True
CORS_ORIGINS=http://localhost:5173
UPDATER_API_URL=http://127.0.0.1:8000
MCP_ALLOWED_HOSTS=api.example.com
OPENROUTER_API_KEY=
LLM_MODEL=google/gemini-3.5-flash-lite
```

- Omit `DATABASE_URL` locally for SQLite preview.
- `UPDATER_TOKEN` is required whenever PostgreSQL is configured **until an account exists** — afterwards you may remove it and rely on logins + API keys (the server keeps booting once a user row is present).
- Sign in from the web UI (email + password). Set `ALLOW_OPEN_REGISTRATION=False` after the first account to close sign-ups; the env token keeps working as a fallback either way.
- `postgres://` and `postgresql://` URLs are accepted. Tables are created on startup.
- For separate web/API origins, set `CORS_ORIGINS` to the web origin and build the frontend with `VITE_API_BASE_URL` pointing at the API.
- For a deployed MCP endpoint, set `MCP_ALLOWED_HOSTS` to its public API hostname (bare hostname is enough — any port on it is accepted). The hostname from `UPDATER_API_URL` is used as a fallback for the same check. Without this, every remote `POST /mcp` is rejected with `421 Invalid Host header` before any MCP logic runs.
- Without `OPENROUTER_API_KEY`, questions still work from saved context and say so.
- Never commit `.env`, `*.db`, or tokens. They are gitignored.

## Deploy

See [DEPLOY.md](DEPLOY.md) for Dokploy (Compose app, external Postgres, `compose.dokploy.yml`, `web` on port 80 + `api` on port 8000, HTTPS for both).

```bash
curl -f https://api.example.com/api/health
curl -f https://app.example.com/healthz
```

## API + MCP reference

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/health` | Liveness check |
| GET | `/api/config` | Token-protected config flag |
| GET | `/api/updates?q=&repo=&tag=` | Search + filter updates |
| POST | `/api/updates` | Publish an update (idempotent on `external_id`) |
| GET | `/api/updates/{id}` | Fetch one update with questions + impact notes |
| POST | `/api/updates/{id}/questions` | Ask about an update |
| POST | `/api/updates/{id}/impact-notes` | Record observed impact |
| POST | `/mcp` | MCP tools: `publish_feature`, `list_feature_updates`, `get_feature_update`, `add_feature_impact`, `list_context_requests`, `fulfill_context_request` |
| POST | `/api/auth/register` | Create an account (first login session returned) |
| POST | `/api/auth/login` | Sign in (login session returned) |
| POST | `/api/auth/logout` | Revoke the current login session |
| GET | `/api/auth/me` | Who the current credential belongs to |
| GET/POST | `/api/auth/keys` | List / issue API keys (shown once at creation) |
| DELETE | `/api/auth/keys/{id}` | Revoke an API key |

## Checks

```bash
cd backend && uv run pytest -q
cd frontend && npm run build
```

Backend tests cover idempotent publishing, search, question persistence, and invalid repo URLs.

## Contributing

Issues and PRs are welcome. For big changes, open an issue first to discuss what you want to change.

```bash
git checkout -b rvey/my-feature
# make changes, add tests when it makes sense
cd backend && uv run pytest -q
cd frontend && npm run build
git commit -m "feat: describe the change"
git push -u origin rvey/my-feature
```

- Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).
- Keep secrets out of Git. Use `backend/.env` locally and Dokploy env in prod.
- Screenshots live in `docs/screenshots/` and are referenced by relative path so they render on GitHub.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

- [agent-skills](https://github.com/addyosmani/agent-skills) for the verify-then-ship inspiration.
- shadcn/ui for the component preset.
- **MCP server** — `publish_feature`, `list_feature_updates`, `get_feature_update`, `add_feature_impact` over Streamable HTTP at `/mcp` (stdio fallback included).
- **MCP server** — `publish_feature`, `list_feature_updates`, `get_feature_update`, `add_feature_impact`, plus `list_context_requests` / `fulfill_context_request` for the codebase proxy, over Streamable HTTP at `/mcp` (stdio fallback included).
- **Codebase context via agent proxy** — the app never clones your repos. It asks the connected agent for short excerpts and only receives what it needs.
## Codebase context via the connected agent (proxy)

Updater never clones repositories and never gets full file access. The agent already runs inside your codebase (opencode, Codex, Claude Code), so the app treats it as a **codebase proxy** and only receives the excerpts it needs:

![Update detail with code excerpts sent by the agent and the ask-my-agent button](docs/screenshots/code-context.png)

1. You ask a question that needs code detail, or hit **Ask my agent for code context** in the update view.
2. Updater stores a `context-request` (update + question) and shows it as waiting on your agent.
3. In your project checkout, the agent polls `list_context_requests`, reads the local files, and answers with `fulfill_context_request` — short excerpts (`path`, `content`, `start_line`, `end_line`, max 8 files).
4. Excerpts are saved on the update, shown as **CODE FROM YOUR AGENT**, and included in follow-up answers. Private repos stay private: nothing leaves the agent host except the snippets it chooses to send.

Agents can also attach `code_context` up front in `publish_feature` (1–5 focused snippets). The agent rule for both flows lives in [docs/agent-instructions.md](docs/agent-instructions.md).

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/updates/{id}/context-requests` | Ask the connected agent for code excerpts |
| GET | `/api/context-requests?status=pending&repo=` | Agent polls waiting requests |
| POST | `/api/context-requests/{id}/fulfill` | Agent sends back excerpts (also saved on the update) |

## What gets saved
