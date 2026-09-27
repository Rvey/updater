---
name: updater-impact
description: Record real-world impact for a shipped Updater feature via add_feature_impact. Use when revisiting old features or user reports outcomes.
---

1. Call `list_feature_updates` to find matching update (`get_feature_update` for details).
2. Call `add_feature_impact` with ONE dated, measured observation. One per call, never rephrase expected impact.
