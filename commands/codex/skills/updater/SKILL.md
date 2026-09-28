---
name: updater
description: Updater router. Bare use ships the last verified changes via publish_feature and checks pending context requests; also handles check, impact, and list flows.
---

Route on the user input. `check -> ship` or `check and ship`: run VERIFY-AND-SHIP, then CHECK; match this before plain check. Empty input, or anything about shipping, saving, or logging the last changes (DEFAULT): run SHIP, then CHECK, in this turn. Pending questions or what the app asked: CHECK. Impact, outcomes, or follow-up on old work: IMPACT. Listing, showing, or searching past updates: LIST. Tech debt, rushed decisions, or tech-depth: TECH-DEPTH.

VERIFY-AND-SHIP: inspect relevant git diff and status, run appropriate tests/build or a meaningful manual check, and fix failures before publishing. If verification fails or there are no relevant changes, report that nothing was shipped. On success run SHIP. Use a commit SHA only when it identifies the published code.

SHIP: only for implemented and verified work. Find the last change or changes via git log and git diff. Gather title, summary, repo_url, why, how_it_works, impact, tradeoffs, learning_notes, files_changed, tags, branch, commit_sha, pr_url, author_agent; stable external_id like owner/repo:slug (branch after last slash, lowercased); 1-5 code_context excerpts with path, content, start_line, end_line. Call Updater MCP publish_feature. Report id and title. If unavailable, say NOT recorded.
  Guard: first call list_feature_updates for this repo - if the same feature (same branch, PR, or overlapping files) is already shipped, reuse its key; the server stashes the new commit under it.

CHECK: call list_context_requests (status pending) for the current repo, read needed local files, answer with fulfill_context_request using short excerpts (max 8 files, about 6000 chars each). Never paste secrets or full files.

IMPACT: call list_feature_updates to find the matching update (get_feature_update for details), then add_feature_impact with ONE dated, measured observation. Never rephrase the expected impact.

LIST: call list_feature_updates with the query and summarize; call get_feature_update when one item is asked about.

TECH-DEPTH: scan for tech debt and rushed decisions (git log, git diff, TODO/FIXME/HACK, duplicated logic, missing tests, fragile error handling, hardcoded values, workarounds). For EACH finding call report_tech_debt once with title, scope, description, impact, mitigation, current_state, urgency (low/medium/high/critical), repo_url, file_path, files, tags, branch, commit_sha, author_agent. One call per finding (max ~10). Skip items already in list_tech_debt unless worse.
