---
description: Record real-world impact for a shipped Updater feature
---

Record a real-world outcome for a shipped feature in Updater.

Additional context: $ARGUMENTS

1. Call Updater MCP `list_feature_updates` with a query (feature name, repo, or keyword) to find the matching update. Use `get_feature_update` if you need details.
2. Call `add_feature_impact` with ONE dated, measured observation (latency before/after, error rate, user feedback, adoption, bug caused). One real observation per call.
3. Never rephrase the expected impact from publish time. If no matching update exists, say so.
