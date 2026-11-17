#!/usr/bin/env bash
# macOS/Linux convenience wrapper. The real (cross-platform) logic lives in
# download_models.py — on Windows run scripts\setup_windows.ps1 instead.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python scripts/download_models.py "$@"
