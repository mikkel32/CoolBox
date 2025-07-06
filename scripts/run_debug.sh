#!/usr/bin/env bash
set -e

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Ensure debugpy is available. When SKIP_DEPS=1 we do a lightweight check and
# only install it if missing so running the script without dependencies still
# works.
if [ "$SKIP_DEPS" = "1" ]; then
    python - <<'EOF'
import importlib.util, sys
sys.exit(0 if importlib.util.find_spec("debugpy") else 1)
EOF
    if [ $? -ne 0 ]; then
        echo "debugpy missing; installing because SKIP_DEPS=1" >&2
        python -m pip install --quiet debugpy
    fi
else
    if ! python -c 'import debugpy' >/dev/null 2>&1; then
        echo "debugpy not found; installing..." >&2
        python -m pip install --quiet debugpy
    fi
    python -m pip install --quiet -r requirements.txt
fi

# Choose debug port
DEBUG_PORT=${DEBUG_PORT:-5678}

# Pick a free port starting at DEBUG_PORT
check_port() {
    python - "$1" <<'EOF'
import socket, sys
port = int(sys.argv[1])
s = socket.socket()
try:
    s.bind(("", port))
except OSError:
    sys.exit(1)
else:
    s.close()
    sys.exit(0)
EOF
}

for p in $(seq "$DEBUG_PORT" "$((DEBUG_PORT+10))"); do
    if check_port "$p"; then
        DEBUG_PORT="$p"
        break
    fi
done

# Terminate any previous debugpy listener on this port
if command -v pkill >/dev/null 2>&1; then
    pkill -f "debugpy --listen $DEBUG_PORT" 2>/dev/null || true
fi

# Launch the application waiting for debugger to attach.  If no display
# is available, ``xvfb-run`` provides a virtual framebuffer so Tkinter
# can initialize correctly.
TARGET="${DEBUG_TARGET:-main.py}"

ARGS=(python -Xfrozen_modules=off -m debugpy --listen "$DEBUG_PORT")
if [ "$DEBUG_NOWAIT" = "1" ]; then
    :
else
    ARGS+=(--wait-for-client)
fi
ARGS+=("$TARGET")

if [ -z "$DISPLAY" ]; then
    if command -v xvfb-run >/dev/null 2>&1; then
        exec xvfb-run -a "${ARGS[@]}"
    else
        echo "warning: xvfb-run not found; running without virtual display" >&2
        exec "${ARGS[@]}"
    fi
else
    exec "${ARGS[@]}"
fi
