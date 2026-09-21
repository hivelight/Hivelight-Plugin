#!/usr/bin/env bash
# macOS double-clickable session refresh — use this when the silent refresh
# fails (about once every 30 days when Hivelight's login cookie expires).
set -e

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$PLUGIN_DIR/skills/hivelight/lib/setup.py"

if [ ! -f "$SETUP" ]; then
    echo "[error] Could not find setup.py next to this script at:"
    echo "  $SETUP"
    echo "The plugin folder may be incomplete. Re-run install.command to fix this."
    read -p "Press Enter to close..."
    exit 1
fi

# Find Python 3.10+
PY=""
for CANDIDATE in python3 python; do
    if command -v "$CANDIDATE" >/dev/null 2>&1; then
        if "$CANDIDATE" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >/dev/null 2>&1; then
            PY="$CANDIDATE"
            break
        fi
    fi
done
if [ -z "$PY" ]; then
    echo "[error] Python 3.10+ is not on PATH. Re-run install.command to set things up."
    read -p "Press Enter to close..."
    exit 1
fi

echo "============================================================"
echo "  Hivelight session refresh"
echo "============================================================"
echo ""
echo "Opening a browser. Log in if prompted; otherwise the refresh"
echo "finishes automatically once it reaches the dashboard."
echo ""

if "$PY" "$SETUP"; then
    echo ""
    echo "[done] Session refreshed. Restart Claude Code if it was open."
else
    echo ""
    echo "[error] Refresh did not complete cleanly. Try install.command as a fallback."
fi
read -p "Press Enter to close..."
