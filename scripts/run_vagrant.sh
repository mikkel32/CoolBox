#!/usr/bin/env bash
set -e
if ! command -v vagrant >/dev/null 2>&1; then
    echo "vagrant is required to run the VM" >&2
    exit 1
fi
vagrant up
vagrant ssh -c "cd /vagrant && ./scripts/run_debug.sh"
