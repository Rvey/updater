---
name: updater-check
description: Poll Updater list_context_requests and fulfill with local code excerpts. Use when asked to check Updater or after code changes.
---

1. Call Updater MCP `list_context_requests` (status pending) for current repo.
2. Read needed files locally.
3. Call `fulfill_context_request` with short excerpts {path, content, start_line, end_line}, max 8 files ~6000 chars each.
4. Never paste secrets or full files.
