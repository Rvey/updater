Record a real-world outcome for a shipped feature in Updater.

Extra user context: $@

1. Call Updater MCP `list_feature_updates` to find the matching update (use `get_feature_update` for details).
2. Call `add_feature_impact` with ONE dated, measured observation. One real observation per call, never rephrase expected impact.
