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
   - `external_id`: stable `owner/repo:feature-slug` (slug is branch after last slash, lowercased) so retries do not duplicate
  Guard: first call list_feature_updates for this repo - if the same feature (same branch, PR, or overlapping files) is already shipped, reuse its key; the server stashes the new commit under it.
   - `code_context`: 1-5 focused excerpts `{path, content, start_line, end_line}` with the exact functions/hunks that explain the change
2. Call the Updater MCP tool `publish_feature` with those fields.
3. Report the returned `id`/`title`. If the MCP tool is unavailable, say the update was NOT recorded — never claim it was.
