#!/usr/bin/env bash
set -e
if command -v vagrant >/dev/null 2>&1; then
    exec ./scripts/run_vagrant.sh
elif command -v docker >/dev/null 2>&1; then
    exec ./scripts/run_devcontainer.sh docker
elif command -v podman >/dev/null 2>&1; then
    exec ./scripts/run_devcontainer.sh podman
else
    # Fall back to running locally under debugpy so the app can still be
    # debugged even when no VM backend is installed.
    exec ./scripts/run_debug.sh
fi
