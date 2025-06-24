#!/usr/bin/env bash
set -e
if command -v vagrant >/dev/null 2>&1; then
    exec ./scripts/run_vagrant.sh
elif command -v docker >/dev/null 2>&1; then
    exec ./scripts/run_devcontainer.sh
else
    echo "Neither vagrant nor docker is available" >&2
    exit 1
fi
