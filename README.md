# Updater — your shipping memory

[![License: MIT](https://img.shields.io/badge/License-MIT-lime.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](backend/pyproject.toml)
[![Node 20.19+](https://img.shields.io/badge/node-20.19%2B-green.svg)](frontend/package.json)
[![Works with OpenCode, Codex, Claude Code](https://img.shields.io/badge/agents-OpenCode%20%7C%20Codex%20%7C%20Claude-purple.svg)](docs/agent-instructions.md)

Updater is an open-source shipping log for work done with coding agents. When your agent finishes and checks a feature, it writes down the **what, why, how, expected result, tradeoffs, changed files, and repo link**. You get a searchable workspace where you can review the history, note what actually happened over time, and ask questions inside each update.

> Screenshots below are the real app running locally with demo content.

## Screenshots

### The real thing — workspace, ship log, and update detail

![Updater workspace showing the ship log with three updates and the update detail pane](docs/screenshots/app-overview.png)

The left column is the searchable ship log. The right pane is the selected update: why it was built, how it works, expected result, files, labels, branch, and commit.

### Work in action — update detail

![Update detail view with why, how it works, impact, tradeoffs, files, and Q&A](docs/screenshots/update-detail.png)

Each update keeps everything in one place: the reason, how it was built, learning notes, changed files, notes on real-world results over time, and a question thread.

### Work in action — instant search

![Typing mcp in search filters the ship log to matching updates](docs/screenshots/search-in-action.png)

Search filters as you type across titles, summaries, code explanations, labels, and repos.

### Work in action — connect an agent in one command

![Connect an agent dialog with copyable commands for OpenCode, Codex, and Claude Code](docs/screenshots/connect-agent.png)

Run one command in your terminal and your agent can publish to Updater and read from it. No settings files to edit by hand.

## Features

- **Ship log** — browse, search, and filter every finished, checked feature.
- **Update detail** — why it was built, how it works, what it changes, tradeoffs, learning notes, files, labels, branch, commit, PR link.
- **Results over time** — add dated notes when you learn what a feature actually changed in practice.
- **Questions per update** — ask about a feature later; answers stay attached to it.
- **Code snippets on demand** — the app asks your agent for the exact code excerpts it needs (see below).
- **Add manually** — record an update from the UI when no agent was involved.
- **Login password (token)** — optionally protect your workspace with a shared secret.
- **Simple local setup, Postgres for hosting** — try it with zero setup; connect a Postgres database when you deploy.
- **Docker hosting ready** — ships with a config for Dokploy (`compose.dokploy.yml`).

## How it works

1. Your coding agent (OpenCode, Codex, Claude Code, …) finishes a feature and checks that it works.
2. Before replying, the agent sends an update to Updater through its built-in agent connection (the open MCP standard — you only ever run one command to set it up).
3. The update lands in your ship log with the story behind the code.
4. Later, when a question needs code detail, Updater asks the agent — which already works inside your codebase — to send just the relevant snippets. The app itself never downloads your code.

## Quickstart

You need Node.js 20.19+ or 22.12+, Python 3.11+, and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Start the data service (terminal 1)
cd backend
uv sync --extra test
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 2. Start the website (terminal 2)
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. On first run the service creates a small local database file (`backend/updater.db`) automatically. Technical docs for the service: <http://127.0.0.1:8000/docs>. Health check: <http://127.0.0.1:8000/api/health>.

## Connect an agent

Start the data service, then run **one** of these in your terminal. If you hosted Updater elsewhere, swap in your own address ending in `/mcp`.

```bash
opencode mcp add updater --global --url http://127.0.0.1:8000/mcp
codex mcp add updater --url http://127.0.0.1:8000/mcp
claude mcp add --transport http --scope user updater http://127.0.0.1:8000/mcp
```

Check it worked with `opencode mcp list`, `codex mcp list`, or `claude mcp list`. The in-app **Connect an agent** dialog builds the same commands for any address.

If you set a password (`UPDATER_TOKEN`) on the service, sign in with it where you start your agent and use the matching secure command:

```bash
export UPDATER_TOKEN='your-long-random-secret'
opencode mcp add updater --global --url http://127.0.0.1:8000/mcp --header 'Authorization=Bearer {env:UPDATER_TOKEN}'
codex mcp add updater --url http://127.0.0.1:8000/mcp --bearer-token-env-var UPDATER_TOKEN
claude mcp add --transport http --scope user updater http://127.0.0.1:8000/mcp --header "Authorization: Bearer $UPDATER_TOKEN"
```

Note: Claude Code stores the password inside its own settings file — treat that file like a credential.

Then copy the short rule in [docs/agent-instructions.md](docs/agent-instructions.md) into your project's instruction file (`AGENTS.md` or `CLAUDE.md`). It tells the agent to record an update **after finished work is checked**, with a stable id (like `owner/repo:commit:feature-name`) so retrying never creates duplicates.

## Code snippets through your agent

Updater never downloads your code and never sees your whole project. Your agent already works inside your codebase, so the app asks *it* for help and only receives the snippets it needs:

![Update detail with code excerpts sent by the agent and the ask-my-agent button](docs/screenshots/code-context.png)

1. You ask a question that needs code detail, or press **Ask my agent for code context**.
2. Updater saves a request (update + question) and shows it as waiting on your agent.
3. In your project folder, the agent looks up waiting requests, reads the local files, and sends back short excerpts (file name, snippet, line numbers — at most 8 files).
4. The excerpts appear on the update under **CODE FROM YOUR AGENT** and are used in follow-up answers. Private projects stay private: nothing leaves the agent's computer except the snippets it chooses to send.

Agents can also attach 1–5 focused snippets right away when recording a feature. The agent-side rules for both flows live in [docs/agent-instructions.md](docs/agent-instructions.md).

For developers — the three helper endpoints:

| What | Address | Purpose |
| --- | --- | --- |
| Ask | `POST /api/updates/{id}/context-requests` | Request code excerpts from the agent |
| Poll | `GET /api/context-requests?status=pending&repo=` | Agent picks up waiting requests |
| Reply | `POST /api/context-requests/{id}/fulfill` | Agent sends back excerpts (saved on the update) |

## What gets saved

Title, summary, repo link, reason, how-it-works explanation, expected result, optional tradeoffs and learning notes, changed files, labels, agent name, branch, commit, PR link, and ship date. Dated result notes and question threads stay attached to the update. You can also add updates by hand from the UI.

## Settings

For local trying-out you need nothing. To host it or turn on extras, copy `backend/.env.example` to `backend/.env`:

```dotenv
DATABASE_URL=postgresql://user:password@host:5432/updater?sslmode=require
UPDATER_TOKEN=your-long-random-secret
CORS_ORIGINS=http://localhost:5173
UPDATER_API_URL=http://127.0.0.1:8000
MCP_ALLOWED_HOSTS=
OPENROUTER_API_KEY=
LLM_MODEL=google/gemini-3.5-flash-lite
```

- Leave out `DATABASE_URL` on your own machine to use the automatic local database.
- `UPDATER_TOKEN` is the workspace password; it is required when you connect Postgres.
- If the website and the data service live on different addresses, point `CORS_ORIGINS` at the website and `VITE_API_BASE_URL` at the service when building.
- For a hosted setup, set `MCP_ALLOWED_HOSTS` to the service's public address.
- Without `OPENROUTER_API_KEY`, questions are still answered from the saved update text and say so.
- Never save passwords or database files in Git. They are already ignored.

Built with React + Vite (website) and Python FastAPI (data service). Postgres for hosting, automatic local database for trying out. Smarter AI answers are optional via OpenRouter.

## Hosting

See [DEPLOY.md](DEPLOY.md) for Dokploy hosting (one app with a `web` part on port 80 and an `api` part on port 8000, both with HTTPS).

```bash
curl -f https://api.example.com/api/health
curl -f https://app.example.com/healthz
```

## Developer reference

| What | Address | Purpose |
| --- | --- | --- |
| Check | `GET /api/health` | See if the service is running |
| Settings | `GET /api/config` | Check setup (needs password) |
| Search | `GET /api/updates` | Search and filter updates |
| Publish | `POST /api/updates` | Record an update (safe to retry — resending the same id won't duplicate) |
| Read one | `GET /api/updates/{id}` | Full update with questions and result notes |
| Ask | `POST /api/updates/{id}/questions` | Ask about an update |
| Note result | `POST /api/updates/{id}/impact-notes` | Record what actually happened |
| Agent link | `POST /mcp` | The connection agents use (publish, list, read, note results, request code, send code) |

## Checks

```bash
cd backend && uv run pytest -q
cd frontend && npm run build
```

The backend checks cover duplicate-safe publishing, search, saved questions, and rejected bad repo links.

## Contributing

Bug reports and pull requests are welcome. For big changes, open an issue first to talk it through.

```bash
git checkout -b rvey/my-feature
# make your changes; add checks where it makes sense
cd backend && uv run pytest -q
cd frontend && npm run build
git commit -m "feat: describe the change"
git push -u origin rvey/my-feature
```

- Write commit messages like `feat: ...` or `fix: ...` ([Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)).
- Keep passwords out of Git. Use `backend/.env` on your machine and your host's settings page in production.
- Screenshots live in `docs/screenshots/` and use relative paths so they show on GitHub.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

- [agent-skills](https://github.com/addyosmani/agent-skills) for the check-then-record inspiration.
