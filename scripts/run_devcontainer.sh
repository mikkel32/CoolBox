#!/usr/bin/env bash
set -e

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required to run the dev container" >&2
    exit 1
fi

IMAGE_NAME=coolbox-dev
CONTAINER_NAME=coolbox_dev

# Build image
docker build -f .devcontainer/Dockerfile -t $IMAGE_NAME .

# Run container and start app under debugpy
RUN_CMD="python -Xfrozen_modules=off -m debugpy --listen 5678 --wait-for-client main.py"
if [ -z "$DISPLAY" ]; then
    if command -v xvfb-run >/dev/null 2>&1; then
        RUN_CMD="xvfb-run -a $RUN_CMD"
    else
        echo "warning: xvfb-run not found; running without virtual display" >&2
    fi
fi
exec docker run --rm \
    --name $CONTAINER_NAME \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v "$(pwd)":/workspace \
    -w /workspace \
    $IMAGE_NAME \
    bash -c "$RUN_CMD"
