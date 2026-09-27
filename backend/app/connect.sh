#!/usr/bin/env bash
# Updater one-step connect: adds the `updater` MCP server AND installs
# /updater-ship, /updater-check, /updater-impact commands for each agent.
# Compatible agents: opencode, codex, claude, cursor.
#
# Why this exists: `opencode mcp add` / `codex mcp add` / `claude mcp add`
# only register the MCP server — they cannot register slash commands.
# (Cursor has no MCP CLI at all; its ~/.cursor/mcp.json is edited directly.)
# This script runs that MCP step and then writes the command files, so one
# terminal command does both.
#
# Non-interactive (flags do both steps, no prompts):
#   bash commands/install.sh --url http://127.0.0.1:8000/mcp --agents all --scope global
#   bash commands/install.sh --url https://api.example.com/mcp --agents opencode,cursor --scope project --project-dir /path/to/repo
#   UPDATER_TOKEN=secret bash commands/install.sh --url https://api.example.com/mcp --agents all
#   bash commands/install.sh --url http://127.0.0.1:8000/mcp --token my-secret --agents claude
#   curl -fsSL https://api.example.com/connect.sh | bash -s -- --url https://api.example.com/mcp --agents all -y
#
# Interactive (prompts for token, then agent selection, for anything not flagged):
#   curl -fsSL https://api.example.com/connect.sh | bash
#   bash commands/install.sh
#
set -e

MCP_URL=''
AGENTS='all'
AGENTS_GIVEN=0
SCOPE='global'
SCOPE_GIVEN=0
PROJECT_DIR="$PWD"
TOKEN=''
SKIP_MCP=0
SKIP_COMMANDS=0
DRY_RUN=0
NONINTERACTIVE=0
FORCE_INTERACTIVE=0

usage() {
  sed -n "1,60p" "$0"
  echo ""
  echo "Flags:"
  echo "  --url URL            MCP server URL ending in /mcp (required)"
  echo '  --agents LIST        all (default) or comma list: opencode,codex,claude,cursor'
  echo '                       numbers 1-4 also work: 1=opencode 2=codex 3=claude 4=cursor'
  echo "  --scope SCOPE        global (default) or project"
  echo "  --project-dir DIR    target repo for --scope project (default: PWD)"
  echo "  --token TOKEN        embed this token in MCP config (insecure, saved to disk/history)"
  echo '                       default: use UPDATER_TOKEN env-var reference when set, else prompt'
  echo "  --skip-mcp           only install slash commands"
  echo '  --skip-commands      only set up MCP'
  echo "  --dry-run            print actions without executing"
  echo '  -y, --yes            non-interactive: never prompt, fail if --url is missing'
  echo '  --interactive        force interactive prompts when a terminal is available'
  echo "  -h, --help           show this help"
  echo ''
  echo 'Env: UPDATER_TOKEN (used by reference when --token is absent)'
  echo '     UPDATER_CONNECT_NO_TTY=1 (read prompts from stdin instead of /dev/tty)'
  echo '     UPDATER_CONNECT_FORCE_STDIN=1 (answer prompts from stdin; for pipes and CI)'
}

log() { printf "%s\n" "$*"; }
run() {
  if [ "$DRY_RUN" = "1" ]; then printf "[dry-run] %s\n" "$*"; else eval "$*"; fi
}
has() { command -v "$1" >/dev/null 2>&1; }
wants() {
  case ",$AGENTS," in *,all,*|*,"$1",*) return 0;; *) return 1;; esac
}

can_prompt() {
  if [ "${UPDATER_CONNECT_NO_TTY:-}" = "1" ]; then return 1; fi
  if [ "${UPDATER_CONNECT_FORCE_STDIN:-}" = "1" ]; then return 0; fi
  if [ -r /dev/tty ]; then return 0; fi
  if [ -t 0 ]; then return 0; fi
  return 1
}
read_from_tty() {
  if use_tty; then IFS= read -r "$1" < /dev/tty || true; else IFS= read -r "$1" || true; fi
}
use_tty() {
  if [ "${UPDATER_CONNECT_FORCE_STDIN:-}" = "1" ]; then return 1; fi
  [ -r /dev/tty ]
}
ask() {
  if can_prompt; then
    printf '%s' "$2" >&2
    read_from_tty answer_value
    if [ -z "${answer_value:-}" ]; then answer_value="$3"; fi
    printf -v "$1" '%s' "$answer_value"
  else
    printf -v "$1" '%s' "$3"
  fi
}
ask_secret() {
  if can_prompt; then
    if use_tty; then
      printf '%s' "$2" > /dev/tty
      IFS= read -rs "$1" < /dev/tty || true
      printf '\n' > /dev/tty
    else
      printf '%s' "$2"
      IFS= read -rs "$1" || true
      printf '\n'
    fi
  else
    printf -v "$1" '%s' ''
  fi
}
map_agent_token() {
  case "$1" in
    1|opencode) printf 'opencode';;
    2|codex) printf 'codex';;
    3|claude) printf 'claude';;
    4|cursor) printf 'cursor';;
    *) return 1;;
  esac
}
normalize_agents() {
  raw_input="$1"
  lowered="$(printf '%s' "$raw_input" | tr '[:upper:]' '[:lower:]' | tr ',;' '  ')"
  if [ -z "$(printf '%s' "$lowered" | tr -d ' \t')" ]; then printf 'all'; return 0; fi
  normalized=''
  for tok in $lowered; do
    case "$tok" in
      all|a|\*) printf 'all'; return 0;;
    esac
    if mapped="$(map_agent_token "$tok")"; then
      case ",$normalized," in *,"$mapped",*) ;; *) normalized="$normalized${normalized:+,}$mapped";; esac
    else
      return 1
    fi
  done
  if [ -z "$normalized" ]; then return 1; fi
  printf '%s' "$normalized"
}
select_agents() {
  log 'Compatible code agents:'
  log '  1) opencode - MCP via CLI, commands in ~/.config/opencode/commands'
  log '  2) codex    - MCP via CLI, prompts and skills in ~/.codex'
  log '  3) claude   - MCP via CLI, commands in ~/.claude/commands'
  log '  4) cursor   - MCP via ~/.cursor/mcp.json, commands in ~/.cursor/commands'
  tries=0
  while [ "$tries" -lt 3 ]; do
    ask selected_answer 'Select agents [1-4, names, comma-separated, Enter for all]: ' 'all'
    if normalized_agents="$(normalize_agents "$selected_answer")"; then
      AGENTS="$normalized_agents"
      return 0
    fi
    log "Could not understand '$selected_answer'. Try e.g. '1,4' or 'opencode,cursor'."
    tries=$((tries + 1))
  done
  AGENTS='all'
  log 'Keeping default: all agents.'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --url) MCP_URL="$2"; shift 2;;
    --agents) AGENTS="$2"; AGENTS_GIVEN=1; shift 2;;
    --scope) SCOPE="$2"; SCOPE_GIVEN=1; shift 2;;
    --project-dir) PROJECT_DIR="$2"; shift 2;;
    --token) TOKEN="$2"; shift 2;;
    --skip-mcp) SKIP_MCP=1; shift;;
    --skip-commands) SKIP_COMMANDS=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    -y|--yes) NONINTERACTIVE=1; shift;;
    --interactive) FORCE_INTERACTIVE=1; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown flag: $1" >&2; usage >&2; exit 1;;
  esac
done

INTERACTIVE=0
if [ "$NONINTERACTIVE" != "1" ]; then
  if [ "$FORCE_INTERACTIVE" = "1" ] || can_prompt; then INTERACTIVE=1; fi
fi

if [ -z "$MCP_URL" ]; then
  if [ "$INTERACTIVE" = "1" ]; then
    ask MCP_URL 'Updater MCP URL [http://127.0.0.1:8000/mcp]: ' 'http://127.0.0.1:8000/mcp'
  else
    echo "Missing --url (e.g. --url http://127.0.0.1:8000/mcp)" >&2; exit 1
  fi
fi
case "$MCP_URL" in */mcp) ;; *) log "WARNING: MCP URL usually ends in /mcp (got $MCP_URL).";; esac

AUTH_MODE="none"
if [ -n "$TOKEN" ]; then
  AUTH_MODE="embedded"
  log "WARNING: --token embeds the secret in MCP config and shell history. Prefer UPDATER_TOKEN env-var when possible."
elif [ -n "${UPDATER_TOKEN:-}" ]; then
  AUTH_MODE="env"
  log "Using token from UPDATER_TOKEN environment (stored by reference, not pasted)."
elif [ "$INTERACTIVE" = "1" ]; then
  ask_secret TOKEN 'Updater token (paste upk_... or server token, Enter to skip): '
  if [ -n "$TOKEN" ]; then
    AUTH_MODE="embedded"
    log "WARNING: the entered token will be saved in MCP config files. Prefer UPDATER_TOKEN env-var on shared machines."
  fi
fi
if [ "$AUTH_MODE" = "env" ]; then
  log "NOTE: Claude Code saves the expanded Authorization header to its MCP settings file — protect that file like a credential."
  log "NOTE: restart Cursor completely after changing its mcp.json so it picks up the MCP server."
fi

if [ "$AGENTS_GIVEN" != "1" ] && [ "$INTERACTIVE" = "1" ]; then
  select_agents
else
  if normalized_agents="$(normalize_agents "$AGENTS")"; then
    AGENTS="$normalized_agents"
  else
    echo "Invalid --agents value: $AGENTS (use e.g. --agents opencode,cursor)" >&2; exit 1
  fi
fi

if [ "$SCOPE_GIVEN" != "1" ] && [ "$INTERACTIVE" = "1" ]; then
  ask scope_answer 'Install scope [global/project, default global]: ' 'global'
  case "$(printf '%s' "$scope_answer" | tr '[:upper:]' '[:lower:]')" in
    global|g|'') SCOPE="global";;
    project|p) SCOPE="project";;
    *) log 'Unknown scope, using global.'; SCOPE="global";;
  esac
fi
case "$SCOPE" in global|project) ;; *) echo "--scope must be global or project" >&2; exit 1;; esac
if [ "$SCOPE" = "project" ]; then
  log "Project target: $PROJECT_DIR"
fi

# ---- MCP add ----
add_mcp_opencode() {
  if ! has opencode; then log "skip opencode mcp: binary not found"; return 0; fi
  cmd="opencode mcp add updater"
  if [ "$SCOPE" = "global" ]; then cmd="$cmd --global"; fi
  cmd="$cmd --url \"$MCP_URL\""
  if [ "$AUTH_MODE" = "embedded" ]; then cmd="$cmd --header \"Authorization=Bearer $TOKEN\"";
  elif [ "$AUTH_MODE" = "env" ]; then cmd="$cmd --header \"Authorization=Bearer {env:UPDATER_TOKEN}\""; fi
  log "→ $cmd"; run "$cmd || true"
}
add_mcp_codex() {
  if ! has codex; then log "skip codex mcp: binary not found"; return 0; fi
  cmd="codex mcp add updater --url \"$MCP_URL\""
  if [ "$AUTH_MODE" = "embedded" ]; then cmd="$cmd --bearer-token \"$TOKEN\"";
  elif [ "$AUTH_MODE" = "env" ]; then cmd="$cmd --bearer-token-env-var UPDATER_TOKEN"; fi
  log "→ $cmd"; run "$cmd || true"
  log "  (codex mcp add writes user config; no separate project/global flag)"
}
add_mcp_claude() {
  if ! has claude; then log "skip claude mcp: binary not found"; return 0; fi
  scope_flag="--scope user"; if [ "$SCOPE" = "project" ]; then scope_flag="--scope project"; fi
  cmd="claude mcp add --transport http $scope_flag updater \"$MCP_URL\""
  if [ "$AUTH_MODE" = "embedded" ]; then cmd="$cmd --header \"Authorization: Bearer $TOKEN\"";
  elif [ "$AUTH_MODE" = "env" ]; then cmd="$cmd --header \"Authorization: Bearer $UPDATER_TOKEN\""; fi
  log "→ $cmd"; run "$cmd || true"
}

# ---- command file writers (self-contained: no repo checkout needed) ----
add_mcp_cursor() {
  if [ "$SCOPE" = "global" ]; then mcp_file="$HOME/.cursor/mcp.json"; else mcp_file="$PROJECT_DIR/.cursor/mcp.json"; fi
  if [ "$DRY_RUN" = "1" ]; then log "[dry-run] merge updater MCP into $mcp_file"; return 0; fi
  if ! has python3; then
    log "skip cursor mcp: python3 not found. Add manually to $mcp_file:"
    log "{\"mcpServers\": {\"updater\": {\"url\": \"$MCP_URL\"}}}"
    return 0
  fi
  UPDATER_MCP_URL="$MCP_URL" UPDATER_MCP_FILE="$mcp_file" UPDATER_MCP_TOKEN="$TOKEN" UPDATER_AUTH_MODE="$AUTH_MODE" python3 - <<'PYEOF'
import json, os
path = os.environ["UPDATER_MCP_FILE"]
url = os.environ["UPDATER_MCP_URL"]
mode = os.environ.get("UPDATER_AUTH_MODE", "none")
token = os.environ.get("UPDATER_MCP_TOKEN", "")
try:
    with open(path) as f:
        data = json.load(f)
except (FileNotFoundError, ValueError):
    data = {}
if not isinstance(data, dict):
    data = {}
servers = data.get("mcpServers")
if not isinstance(servers, dict):
    servers = {}
    data["mcpServers"] = servers
entry = {"url": url}
if mode == "embedded":
    entry["headers"] = {"Authorization": "Bearer " + token}
elif mode == "env":
    entry["headers"] = {"Authorization": "Bearer ${env:UPDATER_TOKEN}"}
servers["updater"] = entry
parent = os.path.dirname(path)
if parent:
    os.makedirs(parent, exist_ok=True)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("wrote " + path)
PYEOF
  log "Restart Cursor completely so it picks up the MCP server."
}

write_file() { dest="$1"; if [ "$DRY_RUN" = "1" ]; then printf "[dry-run] write %s\n" "$dest"; else mkdir -p "$(dirname "$dest")"; cat > "$dest"; log "wrote $dest"; fi; }

install_claude() {
  if [ "$SCOPE" = "global" ]; then base="$HOME/.claude/commands"; else base="$PROJECT_DIR/.claude/commands"; fi
  if [ "$DRY_RUN" != "1" ]; then mkdir -p "$base"; fi
  write_file "$base/updater-ship.md" <<'CMD_EOF'
---
description: Ship verified work to Updater (publish_feature with code context)
---

Publish the just-finished, verified work to Updater via MCP.

Only run after implementation is verified (tests/build/manual check). Do not run for unfinished work, exploration, or failed attempts.

Additional context from user: $ARGUMENTS

1. Gather facts from the current checkout (do not invent):
   - `title`, `summary` (1-2 sentences)
   - `repo_url`: HTTPS remote (e.g. from `git remote get-url origin`)
   - `why`: problem/request that motivated it
   - `how_it_works`: real code path in plain language
   - `impact`: expected user/system impact
   - `tradeoffs`, `learning_notes` (key code path to teach the owner)
   - `files_changed`, `tags`
   - `branch`, `commit_sha`, `pr_url`, `author_agent` when available
   - `external_id`: stable `owner/repo:commit-sha:feature-slug` so retries do not duplicate
   - `code_context`: 1-5 focused excerpts `{path, content, start_line, end_line}` with the exact functions/hunks that explain the change
2. Call the Updater MCP tool `publish_feature` with those fields.
3. Report the returned `id`/`title`. If the MCP tool is unavailable, say the update was NOT recorded — never claim it was.
CMD_EOF
  write_file "$base/updater-check.md" <<'CMD_EOF'
---
description: Check Updater context requests and answer with local code excerpts
---

Check Updater for pending codebase-proxy requests and fulfill them from this checkout.

Additional context: $ARGUMENTS

1. Call Updater MCP `list_context_requests` for the current repo (use `git remote get-url origin` to identify it, `status: pending`).
2. For each pending request, read the needed files locally.
3. Call `fulfill_context_request` with short excerpts only: `{path, content, start_line, end_line}`, max 8 files, ~6000 chars each, only the functions/hunks needed to answer the stored question.
4. Never paste secrets, tokens, or full files. Summarize what you sent.
CMD_EOF
  write_file "$base/updater-impact.md" <<'CMD_EOF'
---
description: Record real-world impact for a shipped Updater feature
---

Record a real-world outcome for a shipped feature in Updater.

Additional context: $ARGUMENTS

1. Call Updater MCP `list_feature_updates` with a query (feature name, repo, or keyword) to find the matching update. Use `get_feature_update` if you need details.
2. Call `add_feature_impact` with ONE dated, measured observation (latency before/after, error rate, user feedback, adoption, bug caused). One real observation per call.
3. Never rephrase the expected impact from publish time. If no matching update exists, say so.
CMD_EOF
  write_file "$base/updater.md" <<'CMD_EOF'
---
description: Updater router - bare command ships last verified changes, or check, impact, list flows
---

You are the Updater router. Updater MCP tools: publish_feature, list_context_requests, fulfill_context_request, list_feature_updates, get_feature_update, add_feature_impact.

User input: $ARGUMENTS (may be empty).

Route on the input:
- Empty, or about shipping, saving, or logging the last changes (DEFAULT): run SHIP, then CHECK, in this turn.
- About pending questions, what the app asked, or check: run CHECK.
- About impact, outcomes, results, or follow-up on old work: run IMPACT.
- About listing, showing, or searching past updates: run LIST.

Flows:
- SHIP: only for implemented and verified work (tests, build, or manual check). Find the last change or changes via git log and git diff. Gather title, summary, repo_url (HTTPS remote), why, how_it_works (real code path), impact, tradeoffs, learning_notes, files_changed, tags, branch, commit_sha, pr_url, author_agent; stable external_id like owner/repo:sha:slug; 1-5 code_context excerpts with path, content, start_line, end_line. Call publish_feature. Report id and title. If the MCP tool is unavailable, say the update was NOT recorded.
- CHECK: call list_context_requests (status pending) for the current repo, read the needed local files, answer with fulfill_context_request using short excerpts (max 8 files, about 6000 chars each). Never paste secrets, tokens, or full files.
- IMPACT: call list_feature_updates to find the matching update (get_feature_update for details), then add_feature_impact with ONE dated, measured observation. Never rephrase the expected impact.
- LIST: call list_feature_updates with the query and summarize; call get_feature_update when one item is asked about.

Never invent facts. Use git history and local files.
CMD_EOF
}

install_opencode() {
  if [ "$SCOPE" = "global" ]; then base="$HOME/.config/opencode/commands"; else base="$PROJECT_DIR/.opencode/commands"; fi
  if [ "$DRY_RUN" != "1" ]; then mkdir -p "$base"; fi
  write_file "$base/updater-ship.md" <<'CMD_EOF'
---
description: Ship verified work to Updater (publish_feature with code context)
---

Publish the just-finished, verified work to Updater via MCP.

Only run after implementation is verified (tests/build/manual check). Do not run for unfinished work, exploration, or failed attempts.

1. Gather facts from the current checkout (do not invent):
   - `title`, `summary` (1-2 sentences)
   - `repo_url`: HTTPS remote (e.g. from `git remote get-url origin`)
   - `why`, `how_it_works` (real code path), `impact`, `tradeoffs`, `learning_notes`
   - `files_changed`, `tags`, `branch`, `commit_sha`, `pr_url`, `author_agent` when available
   - `external_id`: stable `owner/repo:commit-sha:feature-slug`
   - `code_context`: 1-5 focused excerpts `{path, content, start_line, end_line}`
2. Call the Updater MCP tool `publish_feature` with those fields.
3. Report the returned `id`/`title`. If the MCP tool is unavailable, say the update was NOT recorded.
CMD_EOF
  write_file "$base/updater-check.md" <<'CMD_EOF'
---
description: Check Updater context requests and answer with local code excerpts
---

Check Updater for pending codebase-proxy requests and fulfill them from this checkout.

1. Call Updater MCP `list_context_requests` for the current repo (`status: pending`).
2. For each pending request, read needed files locally.
3. Call `fulfill_context_request` with short excerpts `{path, content, start_line, end_line}` (max 8 files, ~6000 chars each).
4. Never paste secrets, tokens, or full files.
CMD_EOF
  write_file "$base/updater-impact.md" <<'CMD_EOF'
---
description: Record real-world impact for a shipped Updater feature
---

Record a real-world outcome for a shipped feature in Updater.

1. Call Updater MCP `list_feature_updates` to find the matching update (use `get_feature_update` for details if needed).
2. Call `add_feature_impact` with ONE dated, measured observation. One real observation per call, never a rephrase of expected impact.
CMD_EOF
  write_file "$base/updater.md" <<'CMD_EOF'
---
description: Updater router - bare command ships last verified changes, or check, impact, list flows
---

You are the Updater router. Updater MCP tools: publish_feature, list_context_requests, fulfill_context_request, list_feature_updates, get_feature_update, add_feature_impact.

User input: whatever follows /updater (may be empty).

Route on the input:
- Empty, or about shipping, saving, or logging the last changes (DEFAULT): run SHIP, then CHECK, in this turn.
- About pending questions, what the app asked, or check: run CHECK.
- About impact, outcomes, results, or follow-up on old work: run IMPACT.
- About listing, showing, or searching past updates: run LIST.

Flows:
- SHIP: only for implemented and verified work (tests, build, or manual check). Find the last change or changes via git log and git diff. Gather title, summary, repo_url (HTTPS remote), why, how_it_works (real code path), impact, tradeoffs, learning_notes, files_changed, tags, branch, commit_sha, pr_url, author_agent; stable external_id like owner/repo:sha:slug; 1-5 code_context excerpts with path, content, start_line, end_line. Call publish_feature. Report id and title. If the MCP tool is unavailable, say the update was NOT recorded.
- CHECK: call list_context_requests (status pending) for the current repo, read the needed local files, answer with fulfill_context_request using short excerpts (max 8 files, about 6000 chars each). Never paste secrets, tokens, or full files.
- IMPACT: call list_feature_updates to find the matching update (get_feature_update for details), then add_feature_impact with ONE dated, measured observation. Never rephrase the expected impact.
- LIST: call list_feature_updates with the query and summarize; call get_feature_update when one item is asked about.

Never invent facts. Use git history and local files.
CMD_EOF
}

install_codex() {
  if [ "$SCOPE" = "global" ]; then prompts="$HOME/.codex/prompts"; skills="$HOME/.codex/skills"; else prompts="$PROJECT_DIR/.codex/prompts"; skills="$PROJECT_DIR/.codex/skills"; fi
  if [ "$DRY_RUN" != "1" ]; then mkdir -p "$prompts" "$skills/updater-ship" "$skills/updater-check" "$skills/updater-impact" "$skills/updater"; fi
  write_file "$prompts/updater-ship.md" <<'CMD_EOF'
Publish the just-finished, verified work to Updater via MCP.

Only run after implementation is verified (tests/build/manual check). Do not run for unfinished work, exploration, or failed attempts.

Extra user context: $@

1. Gather facts from the current checkout (do not invent): title, summary, repo_url (HTTPS remote), why, how_it_works (real code path), impact, tradeoffs, learning_notes, files_changed, tags, branch, commit_sha, pr_url, author_agent when available.
2. Use stable external_id like `owner/repo:commit-sha:feature-slug`.
3. Attach 1-5 focused code_context excerpts {path, content, start_line, end_line}.
4. Call the Updater MCP tool `publish_feature` with those fields.
5. Report returned id/title. If MCP is unavailable, say update was NOT recorded.
CMD_EOF
  write_file "$prompts/updater-check.md" <<'CMD_EOF'
Check Updater for pending codebase-proxy requests and fulfill them from this checkout.

Extra user context: $@

1. Call Updater MCP `list_context_requests` for the current repo (status pending).
2. For each pending request read needed files locally.
3. Call `fulfill_context_request` with short excerpts {path, content, start_line, end_line} (max 8 files, ~6000 chars each).
4. Never paste secrets, tokens, or full files.
CMD_EOF
  write_file "$prompts/updater-impact.md" <<'CMD_EOF'
Record a real-world outcome for a shipped feature in Updater.

Extra user context: $@

1. Call Updater MCP `list_feature_updates` to find the matching update (use `get_feature_update` for details).
2. Call `add_feature_impact` with ONE dated, measured observation. One real observation per call, never rephrase expected impact.
CMD_EOF
  write_file "$skills/updater-ship/SKILL.md" <<'CMD_EOF'
---
name: updater-ship
description: Ship verified work to Updater via publish_feature. Use after a feature is implemented and verified.
---

Publish the just-finished, verified work to Updater via MCP.

Only run after implementation is verified. Do not run for unfinished work or exploration.

1. Gather facts from checkout (do not invent): title, summary, repo_url, why, how_it_works, impact, tradeoffs, learning_notes, files_changed, tags, branch, commit_sha, pr_url, author_agent.
2. Use stable external_id `owner/repo:commit-sha:feature-slug`.
3. Attach 1-5 code_context excerpts {path, content, start_line, end_line}.
4. Call Updater MCP `publish_feature`. Report id/title. If unavailable, say NOT recorded.
CMD_EOF
  write_file "$skills/updater-check/SKILL.md" <<'CMD_EOF'
---
name: updater-check
description: Poll Updater list_context_requests and fulfill with local code excerpts. Use when asked to check Updater or after code changes.
---

1. Call Updater MCP `list_context_requests` (status pending) for current repo.
2. Read needed files locally.
3. Call `fulfill_context_request` with short excerpts {path, content, start_line, end_line}, max 8 files ~6000 chars each.
4. Never paste secrets or full files.
CMD_EOF
  write_file "$skills/updater-impact/SKILL.md" <<'CMD_EOF'
---
name: updater-impact
description: Record real-world impact for a shipped Updater feature via add_feature_impact. Use when revisiting old features or user reports outcomes.
---

1. Call `list_feature_updates` to find matching update (`get_feature_update` for details).
2. Call `add_feature_impact` with ONE dated, measured observation. One per call, never rephrase expected impact.
CMD_EOF
  write_file "$prompts/updater.md" <<'CMD_EOF'
You are the Updater router. Updater MCP tools: publish_feature, list_context_requests, fulfill_context_request, list_feature_updates, get_feature_update, add_feature_impact.

Extra user context: $@ (may be empty).

Route on the input:
- Empty, or about shipping, saving, or logging the last changes (DEFAULT): run SHIP, then CHECK, in this turn.
- About pending questions, what the app asked, or check: run CHECK.
- About impact, outcomes, results, or follow-up on old work: run IMPACT.
- About listing, showing, or searching past updates: run LIST.

Flows:
- SHIP: only for implemented and verified work (tests, build, or manual check). Find the last change or changes via git log and git diff. Gather title, summary, repo_url (HTTPS remote), why, how_it_works (real code path), impact, tradeoffs, learning_notes, files_changed, tags, branch, commit_sha, pr_url, author_agent; stable external_id like owner/repo:sha:slug; 1-5 code_context excerpts with path, content, start_line, end_line. Call publish_feature. Report id and title. If the MCP tool is unavailable, say the update was NOT recorded.
- CHECK: call list_context_requests (status pending) for the current repo, read the needed local files, answer with fulfill_context_request using short excerpts (max 8 files, about 6000 chars each). Never paste secrets, tokens, or full files.
- IMPACT: call list_feature_updates to find the matching update (get_feature_update for details), then add_feature_impact with ONE dated, measured observation. Never rephrase the expected impact.
- LIST: call list_feature_updates with the query and summarize; call get_feature_update when one item is asked about.

Never invent facts. Use git history and local files.
CMD_EOF
  write_file "$skills/updater/SKILL.md" <<'CMD_EOF'
---
name: updater
description: Updater router. Bare use ships the last verified changes via publish_feature and checks pending context requests; also handles check, impact, and list flows.
---

Route on the user input. Empty input, or anything about shipping, saving, or logging the last changes (DEFAULT): run SHIP, then CHECK, in this turn. Pending questions or what the app asked: CHECK. Impact, outcomes, or follow-up on old work: IMPACT. Listing, showing, or searching past updates: LIST.

SHIP: only for implemented and verified work. Find the last change or changes via git log and git diff. Gather title, summary, repo_url, why, how_it_works, impact, tradeoffs, learning_notes, files_changed, tags, branch, commit_sha, pr_url, author_agent; stable external_id like owner/repo:sha:slug; 1-5 code_context excerpts with path, content, start_line, end_line. Call Updater MCP publish_feature. Report id and title. If unavailable, say NOT recorded.

CHECK: call list_context_requests (status pending) for the current repo, read needed local files, answer with fulfill_context_request using short excerpts (max 8 files, about 6000 chars each). Never paste secrets or full files.

IMPACT: call list_feature_updates to find the matching update (get_feature_update for details), then add_feature_impact with ONE dated, measured observation. Never rephrase the expected impact.

LIST: call list_feature_updates with the query and summarize; call get_feature_update when one item is asked about.
CMD_EOF
}

install_cursor() {
  if [ "$SCOPE" = "global" ]; then base="$HOME/.cursor/commands"; else base="$PROJECT_DIR/.cursor/commands"; fi
  if [ "$DRY_RUN" != "1" ]; then mkdir -p "$base"; fi
  write_file "$base/updater-ship.md" <<'CMD_EOF'
# Updater ship - publish verified work to Updater

Publish the just-finished, verified work to Updater via MCP.

Only run after implementation is verified (tests/build/manual check). Do not run for unfinished work, exploration, or failed attempts.

1. Gather facts from the current checkout (do not invent):
   - `title`, `summary` (1-2 sentences)
   - `repo_url`: HTTPS remote (e.g. from `git remote get-url origin`)
   - `why`, `how_it_works` (real code path), `impact`, `tradeoffs`, `learning_notes`
   - `files_changed`, `tags`, `branch`, `commit_sha`, `pr_url`, `author_agent` when available
   - `external_id`: stable `owner/repo:commit-sha:feature-slug`
   - `code_context`: 1-5 focused excerpts `{path, content, start_line, end_line}`
2. Call the Updater MCP tool `publish_feature` with those fields.
3. Report the returned `id`/`title`. If the MCP tool is unavailable, say the update was NOT recorded.
CMD_EOF
  write_file "$base/updater-check.md" <<'CMD_EOF'
# Updater check - answer pending code-context requests

Check Updater for pending codebase-proxy requests and fulfill them from this checkout.

1. Call Updater MCP `list_context_requests` for the current repo (`status: pending`).
2. For each pending request, read needed files locally.
3. Call `fulfill_context_request` with short excerpts `{path, content, start_line, end_line}` (max 8 files, ~6000 chars each).
4. Never paste secrets, tokens, or full files.
CMD_EOF
  write_file "$base/updater-impact.md" <<'CMD_EOF'
# Updater impact - record a real-world outcome

Record a real-world outcome for a shipped feature in Updater.

1. Call Updater MCP `list_feature_updates` to find the matching update (use `get_feature_update` for details if needed).
2. Call `add_feature_impact` with ONE dated, measured observation. One real observation per call, never a rephrase of expected impact.
CMD_EOF
  write_file "$base/updater.md" <<'CMD_EOF'
# Updater - ship last changes, check requests, record impact, or list

You are the Updater router. Updater MCP tools: publish_feature, list_context_requests, fulfill_context_request, list_feature_updates, get_feature_update, add_feature_impact.

User input: whatever follows /updater (may be empty).

Route on the input:
- Empty, or about shipping, saving, or logging the last changes (DEFAULT): run SHIP, then CHECK, in this turn.
- About pending questions, what the app asked, or check: run CHECK.
- About impact, outcomes, results, or follow-up on old work: run IMPACT.
- About listing, showing, or searching past updates: run LIST.

Flows:
- SHIP: only for implemented and verified work (tests, build, or manual check). Find the last change or changes via git log and git diff. Gather title, summary, repo_url (HTTPS remote), why, how_it_works (real code path), impact, tradeoffs, learning_notes, files_changed, tags, branch, commit_sha, pr_url, author_agent; stable external_id like owner/repo:sha:slug; 1-5 code_context excerpts with path, content, start_line, end_line. Call publish_feature. Report id and title. If the MCP tool is unavailable, say the update was NOT recorded.
- CHECK: call list_context_requests (status pending) for the current repo, read the needed local files, answer with fulfill_context_request using short excerpts (max 8 files, about 6000 chars each). Never paste secrets, tokens, or full files.
- IMPACT: call list_feature_updates to find the matching update (get_feature_update for details), then add_feature_impact with ONE dated, measured observation. Never rephrase the expected impact.
- LIST: call list_feature_updates with the query and summarize; call get_feature_update when one item is asked about.

Never invent facts. Use git history and local files.
CMD_EOF
}

log "Updater connect: url=$MCP_URL agents=$AGENTS scope=$SCOPE auth=$AUTH_MODE"
if [ "$SKIP_MCP" != "1" ]; then
  wants opencode && add_mcp_opencode
  wants codex && add_mcp_codex
  wants claude && add_mcp_claude
  wants cursor && add_mcp_cursor
else log "skip mcp add (--skip-mcp)"; fi
if [ "$SKIP_COMMANDS" != "1" ]; then
  wants opencode && install_opencode
  wants codex && install_codex
  wants claude && install_claude
  wants cursor && install_cursor
else log "skip commands (--skip-commands)"; fi
log "done. Verify: opencode/codex/claude mcp list, Cursor Settings -> MCP Tools (green dot), then /updater-ship"
