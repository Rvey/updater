# Updater

Updater is a personal shipping log for work done with coding agents. When an agent finishes and verifies a feature, its MCP tool saves the **what**, **why**, **how**, expected impact, tradeoffs, files, and repository link. The React workspace lets you search the history, record actual impact over time, and ask questions inside each update.

## Stack

- Vite + React + TypeScript
- shadcn/ui with preset `b3YSXDTLsG` (`base-rhea`, zinc, lime primary, Inter/Geist)
- FastAPI + SQLAlchemy
- PostgreSQL via `DATABASE_URL` for persistent deployment; SQLite fallback for local preview
- MCP server over Streamable HTTP at `/mcp` (also available over stdio)

The UI theme and Button component were generated from the requested shadcn preset. The [agent-skills project](https://github.com/addyosmani/agent-skills) informed the verify → ship workflow and the focus on recording decisions; it is not an app dependency.

## Run locally

Requirements: Node.js 20.19+ or 22.12+, Python 3.11+, and [uv](https://docs.astral.sh/uv/).

In one terminal:

```bash
cd backend
uv sync --extra test
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Without a `.env` file, the API creates `backend/updater.db` for a local preview. API docs are at <http://127.0.0.1:8000/docs>.

## Use external PostgreSQL

For Dokploy deployment, see [DEPLOY.md](DEPLOY.md).

Create `backend/.env` from `backend/.env.example` and set your real connection URL and a long random `UPDATER_TOKEN`:

```dotenv
DATABASE_URL=postgresql://user:password@host:5432/updater?sslmode=require
UPDATER_TOKEN=your-long-random-secret
CORS_ORIGINS=http://localhost:5173
```

`postgres://` and `postgresql://` URLs are accepted. The API requires a token whenever PostgreSQL is configured. Database tables are created on startup. If you deploy the frontend and API on separate origins, set `CORS_ORIGINS` to the frontend origin and `VITE_API_BASE_URL` to the API origin when building the frontend. Keep the connection string and token out of Git.

For a deployed MCP endpoint, set `MCP_ALLOWED_HOSTS` to its public hostname (include the port when it is not 80/443). Set `UPDATER_API_URL` to the URL the MCP process can use to reach the FastAPI API, such as `http://127.0.0.1:8000` when both run in the same container. Both settings can be added to `backend/.env`. Loopback hosts are allowed by default for local use.

Optional: set `OPENROUTER_API_KEY` and `LLM_MODEL` in `backend/.env` for conversational explanations through OpenRouter. Without a key, questions still work using the saved feature context and clearly identify that source.

## Connect an agent

Start the API, then run the command for your agent. These commands register Updater through each agent's CLI; you do not need to edit MCP configuration files. OpenCode's `--global` makes it available in every project. Replace the URL with your deployed API's HTTPS `/mcp` URL when connecting from another machine.

```bash
opencode mcp add updater --global --url http://127.0.0.1:8000/mcp
codex mcp add updater --url http://127.0.0.1:8000/mcp
claude mcp add --transport http --scope user updater http://127.0.0.1:8000/mcp
```

Run **one** of these, then check it with `opencode mcp list`, `codex mcp list`, or `claude mcp list`. The app's **Connect an agent** dialog can build and copy the same commands for a different URL.

If `UPDATER_TOKEN` is set on the API, export the same value in the terminal where you run and launch your agent, and use the secured command for that agent:

```bash
export UPDATER_TOKEN='your-long-random-secret'
opencode mcp add updater --global --url http://127.0.0.1:8000/mcp --header 'Authorization=Bearer {env:UPDATER_TOKEN}'
codex mcp add updater --url http://127.0.0.1:8000/mcp --bearer-token-env-var UPDATER_TOKEN
claude mcp add --transport http --scope user updater http://127.0.0.1:8000/mcp --header "Authorization: Bearer $UPDATER_TOKEN"
```

OpenCode resolves `{env:UPDATER_TOKEN}` when it runs; Codex reads the named environment variable. Claude Code's CLI saves the expanded header to its user MCP settings, so protect that file like a credential.

The server exposes `publish_feature`, `list_feature_updates`, `get_feature_update`, and `add_feature_impact`. Installing an MCP server makes the tool available, but does not trigger it after a Git push. Copy the short rule in [docs/agent-instructions.md](docs/agent-instructions.md) into each target repository's `AGENTS.md` or `CLAUDE.md`. That instruction asks the agent to call `publish_feature` after shipped work is verified. Use a stable `external_id` such as `owner/repo:commit-sha:feature-slug`; retries then return the same update.

The older stdio entry point remains available with `cd backend && uv run python -m app.mcp_server` if you need a local subprocess transport. Set `UPDATER_API_URL` to the API origin and `UPDATER_TOKEN` when using it. Updater is not currently published in an MCP marketplace; the CLI commands connect directly to your running server.

## What gets saved

Each update records a title, summary, repo link, reason, implementation explanation, expected impact, optional tradeoffs and learning notes, changed files, tags, agent name, branch, commit, PR link, and shipping date. Dated impact observations and question threads stay attached to the update. The frontend also supports adding an update manually.

## Checks

```bash
cd backend && uv run pytest -q
cd frontend && npm run build
```

The backend tests cover idempotent publishing, search, question persistence, and invalid repository URLs.
