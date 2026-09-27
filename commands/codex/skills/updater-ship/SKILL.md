---
name: updater-ship
description: Ship verified work to Updater via publish_feature. Use after a feature is implemented and verified.
---

Publish the just-finished, verified work to Updater via MCP.

Only run after implementation is verified. Do not run for unfinished work or exploration.

1. Gather facts from checkout (do not invent): title, summary, repo_url, why, how_it_works, impact, tradeoffs, learning_notes, files_changed, tags, branch, commit_sha, pr_url, author_agent.
2. Use stable external_id `owner/repo:feature-slug` (slug is branch after last slash, lowercased).
  Guard: first call list_feature_updates for this repo - if the same feature (same branch, PR, or overlapping files) is already shipped, reuse its key; the server stashes the new commit under it.
3. Attach 1-5 code_context excerpts {path, content, start_line, end_line}.
4. Call Updater MCP `publish_feature`. Report id/title. If unavailable, say NOT recorded.
