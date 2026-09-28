---
description: Scan for tech debt and rushed decisions, report each to Updater
---

Hunt for tech debt and rushed decisions in this checkout, then report each finding to Updater.

Additional context from user: $ARGUMENTS

1. Scan local evidence (do not invent): git log, git diff, TODO/FIXME/HACK markers, duplicated logic, missing tests, fragile error handling, hardcoded values, oversized functions, temporary workarounds.
2. Read the surrounding code for each candidate so the report is factual.
3. Get repo_url from git remote get-url origin (HTTPS form), plus branch and commit_sha when available.
4. For EACH finding call Updater MCP report_tech_debt once with title, scope, description, impact, mitigation, current_state, urgency (low/medium/high/critical), repo_url, file_path, files, tags, branch, commit_sha, author_agent.
5. Report returned id/title/urgency. If MCP is unavailable, say findings were NOT recorded. Skip items already in list_tech_debt unless worse.
