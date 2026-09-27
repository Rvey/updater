---
description: Check Updater context requests and answer with local code excerpts
---

Check Updater for pending codebase-proxy requests and fulfill them from this checkout.

1. Call Updater MCP `list_context_requests` for the current repo (`status: pending`).
2. For each pending request, read needed files locally.
3. Call `fulfill_context_request` with short excerpts `{path, content, start_line, end_line}` (max 8 files, ~6000 chars each).
4. Never paste secrets, tokens, or full files.
