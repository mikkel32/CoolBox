#!/usr/bin/env bash
set -e
if ! command -v vagrant >/dev/null 2>&1; then
    echo "vagrant is required to run the VM" >&2
    exit 1
fi
PORT="${DEBUG_PORT:-5678}"
DEBUG_PORT="$PORT" vagrant up
DEBUG_PORT="$PORT" vagrant ssh -c "cd /vagrant && DEBUG_PORT=$PORT ./scripts/run_debug.sh"
