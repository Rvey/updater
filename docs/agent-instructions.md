# Capture shipped features in Updater

Copy this rule into the `AGENTS.md` and/or `CLAUDE.md` of each repository where you want automatic updates:

> After completing and verifying a user-facing feature, call the Updater MCP tool `publish_feature` before your final response. Record only facts supported by the completed work. Include a concise title and summary, the problem or request that motivated it, an explanation of the actual code path in plain language, expected user or system impact, known tradeoffs, key files, repository HTTPS URL, and useful learning notes. Include the branch, commit SHA, PR link, and agent name when available. Use a stable `external_id` based on repository, commit, and feature so retries do not duplicate the update. Attach 1-5 focused `code_context` excerpts (`path`, `content`, `start_line`, `end_line`) with the exact functions or hunks that explain the change, so follow-up questions can be answered without further file access. If the MCP tool is unavailable, say that the update was not recorded; do not claim it was.

# Answer pending code-context requests (codebase proxy)

Copy this rule too so the app can read your codebase through you — it never clones repos or gets full file access:

> When the user asks you to check Updater (or at the end of any substantive code change), call the Updater MCP tool `list_context_requests` for the current repository. For each pending request, read the needed files from the local checkout and call `fulfill_context_request` with short excerpts: only the functions or hunks required to answer the stored question (max 8 files, ~6000 chars each, with `path`, `content`, `start_line`, `end_line`). Never paste secrets, tokens, or full files. The app stores only the excerpts you send and uses them for follow-up Q&A.

The trigger is **after the feature is shipped and verified**. Routine exploration, unfinished work, and failed attempts do not create an update. The agent should state what it verified in its final response and can include that evidence in the saved learning notes.

# Record real-world impact over time

Copy this rule too so Impact over time actually gets filled — otherwise it stays empty:

> When you revisit a repository days or weeks after a shipped feature (or the user reports an outcome, metric, bug, or follow-up tied to a past change), call the Updater MCP tools `list_feature_updates` to find the matching update, then `add_feature_impact` with one dated observation. Use measured facts when available — e.g. latency before/after, error rates, user feedback, adoption, or bugs caused. Record one note per real observation, not a summary of the expected impact. If the user asks you to check Updater, also look for shipped updates older than a few days with no impact notes and ask whether anything observable has changed.
