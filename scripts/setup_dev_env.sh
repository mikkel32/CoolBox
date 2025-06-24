#!/usr/bin/env bash
set -e
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install debugpy flake8
printf '\nEnvironment ready. Run "code ." and press F5 to debug.\n'
printf 'Use ./scripts/run_debug.sh to start the app in debug mode.\n'
