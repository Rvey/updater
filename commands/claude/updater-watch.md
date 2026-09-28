---
description: Watch Updater context requests and route them to mapped checkouts
---

Route Updater context requests to the right local checkout (registry + notify, optional auto-spawn).

Setup once per checkout: python3 commands/updater-watch.py register --path . [--auto]
List mappings: python3 commands/updater-watch.py list
Watch: python3 commands/updater-watch.py watch --interval 15 [--once] [--auto] [--agent opencode]

Auth via UPDATER_TOKEN env (upk_ key preferred). Only mapped repos are acted on; others are skipped so one checkout never grabs another project's context. Claims expire after 10 minutes.

Additional context: $ARGUMENTS
