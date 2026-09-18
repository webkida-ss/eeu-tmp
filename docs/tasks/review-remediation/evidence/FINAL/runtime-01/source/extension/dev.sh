#!/usr/bin/env bash
# Development helper: auto-reloads the extension in your normal Chrome.
#
# Runs the local reload server (dev/reload-server.mjs), which watches the
# extension source and tells the unpacked extension to reload itself over a
# localhost WebSocket (the client lives at the end of background.js and only
# activates on unpacked installs). No separate browser instance: keep using
# your everyday Chrome profile with the extension loaded via
# chrome://extensions "Load unpacked".
#
# Usage: extension/dev.sh

set -euo pipefail

EXT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec node "$EXT_DIR/dev/reload-server.mjs"
