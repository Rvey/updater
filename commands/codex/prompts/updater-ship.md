Publish the just-finished, verified work to Updater via MCP.

Only run after implementation is verified (tests/build/manual check). Do not run for unfinished work, exploration, or failed attempts.

Extra user context: $@

1. Gather facts from the current checkout (do not invent): title, summary, repo_url (HTTPS remote), why, how_it_works (real code path), impact, tradeoffs, learning_notes, files_changed, tags, branch, commit_sha, pr_url, author_agent when available.
2. Use stable external_id like `owner/repo:commit-sha:feature-slug`.
3. Attach 1-5 focused code_context excerpts {path, content, start_line, end_line}.
4. Call the Updater MCP tool `publish_feature` with those fields.
5. Report returned id/title. If MCP is unavailable, say update was NOT recorded.
