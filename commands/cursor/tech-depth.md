# Tech depth - scan and report tech debt to Updater

Hunt for tech debt and rushed decisions in this checkout, then report each finding to Updater.

1. Scan local evidence (do not invent): git log, git diff, TODO/FIXME/HACK markers, duplicated logic, missing tests, fragile error handling, hardcoded values, oversized functions, temporary workarounds.
2. Read surrounding code for each candidate.
3. Get repo_url from git remote get-url origin (HTTPS), plus branch and commit when available.
4. For EACH finding call Updater MCP report_tech_debt with title, scope, description, impact, mitigation, current_state, urgency (low/medium/high/critical), repo_url, file_path, files, tags, branch, commit_sha, author_agent.
5. Report returned id/title/urgency. If MCP is unavailable, say NOT recorded. Skip items already in list_tech_debt unless worse.
