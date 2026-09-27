# Updater commands — MCP as slash commands

MCP tools do not show up as `/commands` by themselves. These wrappers tell each CLI to call the Updater MCP tools.
## Automatic (recommended): one command does MCP + commands

`mcp add` alone cannot register slash commands, so `commands/install.sh` runs that MCP step AND writes the command files.

```bash
# from this repo (global, all agents)
bash commands/install.sh --url http://127.0.0.1:8000/mcp --agents all --scope global
# one agent, project-only (writes .claude/commands etc. in current repo)
bash commands/install.sh --url http://127.0.0.1:8000/mcp --agents claude --scope project
# secured server via env var (preferred over --token)
UPDATER_TOKEN=secret bash commands/install.sh --url https://api.example.com/mcp --agents all
```

No checkout on the agent machine? The API serves the same script at `GET /connect.sh`:

```bash
curl -fsSL http://127.0.0.1:8000/connect.sh | bash -s -- --url http://127.0.0.1:8000/mcp --agents all
curl -fsSL https://api.example.com/connect.sh | bash -s -- --url https://api.example.com/mcp --agents opencode
```

Run it with no flags for the interactive version — it prompts for the MCP URL (when missing), then the token (silent input, Enter to skip), then which agents to set up (pick one or many: opencode, codex, claude, cursor), then the scope:

```bash
curl -fsSL https://api.example.com/connect.sh | bash
```

Notes:
- Cursor has no `mcp add` CLI, so the script merges the server into `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project), keeping any servers already there. Restart Cursor completely afterwards.
- `--agents` also accepts numbers (`1,4`) and names; `all` (default) covers every agent.

The in-app Connect dialog shows this one-step command per agent (plus an all-agents variant).

Files:
- `claude/updater-*.md` → Claude Code commands
- `opencode/updater-*.md` → OpenCode commands
- `cursor/updater-*.md` → Cursor commands (plain Markdown, no frontmatter needed)
- `codex/prompts/updater-*.md` → Codex prompts (legacy, still works)
- `codex/skills/updater-*/SKILL.md` → Codex skills (preferred going forward)

Commands:
- `updater` → router: bare ships the last verified changes (then checks requests); `updater check` / `updater impact ...` / `updater list ...` for the rest
- `updater-ship` → `publish_feature` (after verified work)
- `updater-check` → `list_context_requests` + `fulfill_context_request`
- `updater-impact` → `list_feature_updates` + `add_feature_impact`

## Install (global, works in every repo)

```bash
# Claude Code
mkdir -p ~/.claude/commands
cp commands/claude/*.md ~/.claude/commands/
# → /updater-ship, /updater-check, /updater-impact (personal commands)

# OpenCode
mkdir -p ~/.config/opencode/commands
cp commands/opencode/*.md ~/.config/opencode/commands/
# → /updater-ship etc.

# Codex — skills (preferred)
mkdir -p ~/.codex/skills
cp -R commands/codex/skills/* ~/.codex/skills/
# Codex — prompts (legacy)
mkdir -p ~/.codex/prompts
cp commands/codex/prompts/*.md ~/.codex/prompts/
```

## Install (project only, shared with team)

```bash
# from repo root
mkdir -p .claude/commands .opencode/commands .codex/prompts .codex/skills
cp commands/claude/*.md .claude/commands/
cp commands/opencode/*.md .opencode/commands/
cp commands/codex/prompts/*.md .codex/prompts/
cp -R commands/codex/skills/* .codex/skills/
```

You still need the MCP connected (`opencode mcp add ...` / `codex mcp add ...` / `claude mcp add ...`). The command just invokes the already-connected `updater` MCP tools.
