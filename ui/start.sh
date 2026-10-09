#!/usr/bin/env bash
# start.sh — launch the Django dev server.
# Port is configurable via TORRENTS_UI_PORT (default 8888).
# Bound to 127.0.0.1 (localhost only).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export TORRENTS_CSV_DIR="${TORRENTS_CSV_DIR:-$HERE/..}"
PORT="${TORRENTS_UI_PORT:-8888}"
exec nix-shell "$HERE/shell.nix" --run "cd $HERE && python manage.py runserver 127.0.0.1:$PORT --noreload"
