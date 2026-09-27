# Updater impact - record a real-world outcome

Record a real-world outcome for a shipped feature in Updater.

1. Call Updater MCP `list_feature_updates` to find the matching update (use `get_feature_update` for details if needed).
2. Call `add_feature_impact` with ONE dated, measured observation. One real observation per call, never a rephrase of expected impact.
