#!/usr/bin/env bash
set -e

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Ensure debugpy is installed
python -m pip install --quiet debugpy

# Launch the application waiting for debugger to attach
exec python -m debugpy --listen 5678 --wait-for-client main.py
