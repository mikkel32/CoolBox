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
exec docker run --rm \
    --name $CONTAINER_NAME \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v "$(pwd)":/workspace \
    -w /workspace \
    $IMAGE_NAME \
    python -m debugpy --listen 5678 --wait-for-client main.py
