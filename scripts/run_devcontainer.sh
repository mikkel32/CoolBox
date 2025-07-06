#!/usr/bin/env bash
set -e

ENGINE="${1:-}"
if [ -z "$ENGINE" ]; then
    if command -v docker >/dev/null 2>&1; then
        ENGINE="docker"
    elif command -v podman >/dev/null 2>&1; then
        ENGINE="podman"
    else
        echo "docker or podman is required to run the dev container" >&2
        exit 1
    fi
fi

IMAGE_NAME=coolbox-dev
CONTAINER_NAME=coolbox_dev
DEBUG_PORT="${DEBUG_PORT:-5678}"
SKIP_DEPS="${SKIP_DEPS:-}"
DEBUG_NOWAIT="${DEBUG_NOWAIT:-}"

# Build image
$ENGINE build -f .devcontainer/Dockerfile -t $IMAGE_NAME .

# Run container and launch application using run_debug.sh
TARGET="${DEBUG_TARGET:-main.py}"
RUN_CMD="./scripts/run_debug.sh"
exec $ENGINE run --rm \
    --name $CONTAINER_NAME \
    -e DISPLAY=$DISPLAY \
    -e DEBUG_PORT=$DEBUG_PORT \
    -e DEBUG_TARGET="$TARGET" \
    -e SKIP_DEPS=$SKIP_DEPS \
    -e DEBUG_NOWAIT=$DEBUG_NOWAIT \
    -p $DEBUG_PORT:$DEBUG_PORT \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v "$(pwd)":/workspace \
    -w /workspace \
    $IMAGE_NAME \
    bash -c "$RUN_CMD"
