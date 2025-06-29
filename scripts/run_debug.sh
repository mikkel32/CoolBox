#!/usr/bin/env bash
set -e

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Ensure debugpy and runtime deps are installed unless SKIP_DEPS=1
if [ "$SKIP_DEPS" != "1" ]; then
    python -m pip install --quiet debugpy
    python -m pip install --quiet -r requirements.txt
fi

# Choose debug port
DEBUG_PORT=${DEBUG_PORT:-5678}

# Terminate any previous debugpy listener on this port
if command -v pkill >/dev/null 2>&1; then
    pkill -f "debugpy --listen $DEBUG_PORT" 2>/dev/null || true
fi

# Launch the application waiting for a debugger to attach. If no display is
# available we try ``pyvirtualdisplay`` first and then ``xvfb-run`` as a
# fallback so Tkinter can initialize correctly in headless environments.
if [ -z "$DISPLAY" ]; then
    if python - "$DEBUG_PORT" <<'EOF'
import sys
import subprocess

port = sys.argv[1]
try:
    from pyvirtualdisplay import Display

    display = Display()
    display.start()
    try:
        subprocess.check_call([
            sys.executable,
            "-Xfrozen_modules=off",
            "-m",
            "debugpy",
            "--listen",
            port,
            "--wait-for-client",
            "main.py",
        ])
    finally:
        display.stop()
except Exception:
    sys.exit(1)
EOF
    then
        exit 0
    elif command -v xvfb-run >/dev/null 2>&1; then
        exec xvfb-run -a python -Xfrozen_modules=off -m debugpy --listen $DEBUG_PORT --wait-for-client main.py
    else
        echo "warning: xvfb-run not found; running without virtual display" >&2
        exec python -Xfrozen_modules=off -m debugpy --listen $DEBUG_PORT --wait-for-client main.py
    fi
else
    exec python -Xfrozen_modules=off -m debugpy --listen $DEBUG_PORT --wait-for-client main.py
fi
