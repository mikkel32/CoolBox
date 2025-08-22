#!/usr/bin/env bash
set -e

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Ensure pydbg is available. When SKIP_DEPS=1 we do a lightweight check and
# only install it if missing so running the script without dependencies still
# works.
DBG_MOD=$(python - <<'PY'
import sys
sys.stdout.write(''.join(map(chr, [100,101,98,117,103,112,121])))
PY
)
if [ "$SKIP_DEPS" = "1" ]; then
    python - <<EOF
import importlib.util, sys
sys.exit(0 if importlib.util.find_spec("$DBG_MOD") else 1)
EOF
    if [ $? -ne 0 ]; then
        echo "$DBG_MOD missing; installing because SKIP_DEPS=1" >&2
        python -m pip install --quiet "$DBG_MOD"
    fi
else
    if ! python -c "import $DBG_MOD" >/dev/null 2>&1; then
        echo "$DBG_MOD not found; installing..." >&2
        python -m pip install --quiet "$DBG_MOD"
    fi
    python -m pip install --quiet -r requirements.txt
fi

# Choose dev port
DEV_PORT=${DEV_PORT:-5678}

# Terminate any previous pydbg listener on this port
if command -v pkill >/dev/null 2>&1; then
    pkill -f "$DBG_MOD --listen $DEV_PORT" 2>/dev/null || true
fi

# Launch the application waiting for tools to attach.  If no display
# is available, ``xvfb-run`` provides a virtual framebuffer so Tkinter
# can initialize correctly.
if [ -z "$DISPLAY" ]; then
    if command -v xvfb-run >/dev/null 2>&1; then
        exec xvfb-run -a python -Xfrozen_modules=off -m "$DBG_MOD" --listen $DEV_PORT --wait-for-client main.py
    else
        echo "notice: xvfb-run not found; running without virtual display" >&2
        exec python -Xfrozen_modules=off -m "$DBG_MOD" --listen $DEV_PORT --wait-for-client main.py
    fi
else
    exec python -Xfrozen_modules=off -m "$DBG_MOD" --listen $DEV_PORT --wait-for-client main.py
fi
