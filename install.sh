#!/usr/bin/env bash
# Linux installer. Run from a terminal:  bash install.sh
set -e

echo "============================================================"
echo "  Hivelight Claude Code Plugin - Installer"
echo "============================================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SCRIPT_DIR/.claude-plugin/marketplace.json" ]; then
    echo "[error] Could not find .claude-plugin/marketplace.json next to this installer."
    exit 1
fi

# ----- Find Python 3.10+ -----
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
    echo "[error] Python 3.10+ is required but not found."
    echo "On Debian/Ubuntu:  sudo apt install python3 python3-pip"
    exit 1
fi
echo "[ok] Found Python: $PY ($($PY --version 2>&1))"
echo ""

# ----- Hand off to the cross-platform installer -----
"$PY" "$SCRIPT_DIR/installer.py" "$SCRIPT_DIR"
