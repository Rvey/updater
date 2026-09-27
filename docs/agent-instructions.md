# Capture shipped features in Updater

Copy this rule into the `AGENTS.md` and/or `CLAUDE.md` of each repository where you want automatic updates:

> After completing and verifying a user-facing feature, call the Updater MCP tool `publish_feature` before your final response. Record only facts supported by the completed work. Include a concise title and summary, the problem or request that motivated it, an explanation of the actual code path in plain language, expected user or system impact, known tradeoffs, key files, repository HTTPS URL, and useful learning notes. Include the branch, commit SHA, PR link, and agent name when available. Use a stable `external_id` based on repository, commit, and feature so retries do not duplicate the update. If the MCP tool is unavailable, say that the update was not recorded; do not claim it was.

The trigger is **after the feature is shipped and verified**. Routine exploration, unfinished work, and failed attempts do not create an update. The agent should state what it verified in its final response and can include that evidence in the saved learning notes.

