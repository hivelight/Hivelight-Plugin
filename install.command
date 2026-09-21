#!/usr/bin/env bash
# macOS double-clickable installer.
set -e

echo "============================================================"
echo "  Hivelight Claude Code Plugin - Installer"
echo "============================================================"
echo ""
echo "This will:"
echo "  1. Verify Claude Code CLI and Python 3.10+ are installed"
echo "  2. Register the Hivelight marketplace with Claude Code"
echo "  3. Install the Hivelight plugin (~30 sec)"
echo "  4. Download a headless browser (~150 MB, 3-5 min)"
echo "  5. Open Hivelight in a browser so you can log in once"
echo ""
read -p "Press Enter to continue, or Ctrl+C to cancel..."
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SCRIPT_DIR/.claude-plugin/marketplace.json" ]; then
    echo "[error] Could not find .claude-plugin/marketplace.json next to this installer."
    echo "        Make sure you fully unzipped the package before running this."
    read -p "Press Enter to close..."
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
    echo "[error] Python 3.10 or later is required but was not found."
    echo ""
    echo "Easiest installs on macOS:"
    echo "  - Download from https://www.python.org/downloads/  (recommended)"
    echo "  - Or:  brew install python"
    echo ""
    echo "After installing, close this window and double-click install.command again."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi
echo "[ok] Found a working Python: $PY ($($PY --version 2>&1))"
echo ""

# ----- Hand off to the cross-platform installer -----
if ! "$PY" "$SCRIPT_DIR/installer.py" "$SCRIPT_DIR"; then
    echo ""
    echo "[error] Installer did not complete cleanly. See the messages above for the"
    echo "        exact failure and the command you can re-run."
    read -p "Press Enter to close..."
    exit 1
fi

echo ""
read -p "Press Enter to close..."
