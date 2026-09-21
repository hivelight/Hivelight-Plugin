#!/usr/bin/env bash
# Linux session refresh.
set -e
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$PLUGIN_DIR/skills/hivelight/lib/setup.py"
if [ ! -f "$SETUP" ]; then
    echo "[error] setup.py not found next to this script ($SETUP). Re-run install.sh."
    exit 1
fi
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
    echo "[error] Python 3.10+ not found."
    exit 1
fi
"$PY" "$SETUP"
