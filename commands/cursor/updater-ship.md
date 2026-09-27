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
