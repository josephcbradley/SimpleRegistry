#!/usr/bin/env bash
set -euo pipefail

WISHLIST="package_wishlist.txt"
DEST="wheelhouse"
PLATFORM="manylinux2014_x86_64"
PYVER="3.12"

rm -rf "$DEST"
mkdir -p "$DEST"

for PLATFORM in manylinux2014_x86_64 win_amd64; do
  uv run pip download \
    -r "$WISHLIST" \
    --dest "$DEST/$PLATFORM" \
    --platform "$PLATFORM" \
    --python-version $PYVER \
    --only-binary :all:
done
