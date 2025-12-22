#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="wheelserver"
TAG="py312"
TAR_NAME="wheelserver_py312.tar"
DOCKERFILE="Dockerfile.wheelserver"

docker build -f "$DOCKERFILE" -t "$IMAGE_NAME:$TAG" .
docker save "$IMAGE_NAME:$TAG" -o "$TAR_NAME"

echo "✔ Image saved to $TAR_NAME"
