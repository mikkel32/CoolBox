#!/usr/bin/env bash
set -e
# This wrapper simply invokes the Python helper so command line options
# like ``--prefer`` or ``--code`` work consistently across platforms.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python "$SCRIPT_DIR/../python/run_vm_debug.py" "$@"
