---
name: tech-depth
description: Scan the checkout for tech debt and rushed decisions, report each to Updater via report_tech_debt. Use when asked to run tech-depth.
---

1. Scan git log, git diff, TODO/FIXME/HACK markers, duplicated logic, missing tests, fragile error handling, hardcoded values, oversized functions, temporary workarounds. Read surrounding code; never invent.
2. Get repo_url (HTTPS remote), branch, commit_sha when available.
3. For EACH finding call Updater MCP report_tech_debt with title, scope, description, impact, mitigation, current_state, urgency (low/medium/high/critical), repo_url, file_path, files, tags, branch, commit_sha, author_agent.
4. Report id/title/urgency. If unavailable, say NOT recorded. Skip items already in list_tech_debt unless worse.
