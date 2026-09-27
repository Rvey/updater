---
name: updater
description: Updater router. Bare use ships the last verified changes via publish_feature and checks pending context requests; also handles check, impact, and list flows.
---

Route on the user input. Empty input, or anything about shipping, saving, or logging the last changes (DEFAULT): run SHIP, then CHECK, in this turn. Pending questions or what the app asked: CHECK. Impact, outcomes, or follow-up on old work: IMPACT. Listing, showing, or searching past updates: LIST.

SHIP: only for implemented and verified work. Find the last change or changes via git log and git diff. Gather title, summary, repo_url, why, how_it_works, impact, tradeoffs, learning_notes, files_changed, tags, branch, commit_sha, pr_url, author_agent; stable external_id like owner/repo:sha:slug; 1-5 code_context excerpts with path, content, start_line, end_line. Call Updater MCP publish_feature. Report id and title. If unavailable, say NOT recorded.

CHECK: call list_context_requests (status pending) for the current repo, read needed local files, answer with fulfill_context_request using short excerpts (max 8 files, about 6000 chars each). Never paste secrets or full files.

IMPACT: call list_feature_updates to find the matching update (get_feature_update for details), then add_feature_impact with ONE dated, measured observation. Never rephrase the expected impact.

LIST: call list_feature_updates with the query and summarize; call get_feature_update when one item is asked about.
