#!/usr/bin/env bash
set -e
# Launch the plugin preview CLI with consistent environment handling.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python "$SCRIPT_DIR/../python/run_plugin_preview.py" "$@"

