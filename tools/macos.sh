#!/bin/bash
set -eo pipefail

ARCHIVE_URL="${MOTHERLODE_ARCHIVE_URL:-https://github.com/BigBadBleuCheese/Motherlode/archive/refs/heads/master.tar.gz}"
APP_DIR="$HOME/Library/Application Support/Motherlode"
OUTPUT="${MOTHERLODE_OUTPUT:-$HOME/Documents/Motherlode}"

echo "Downloading the latest Motherlode..."
rm -rf "$APP_DIR/app.new"
mkdir -p "$APP_DIR/app.new"
curl -fsSL "$ARCHIVE_URL" | tar -xz -C "$APP_DIR/app.new" --strip-components 1
rm -rf "$APP_DIR/app"
mv "$APP_DIR/app.new" "$APP_DIR/app"

MOTHERLODE_OUTPUT="$OUTPUT" exec bash "$APP_DIR/app/Motherlode.command" "$@"
