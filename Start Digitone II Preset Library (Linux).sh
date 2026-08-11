#!/usr/bin/env sh
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR" || exit 1
VENV="$SCRIPT_DIR/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" || exit 1
fi
if ! "$VENV/bin/python" -c "import textual" 2>/dev/null; then
  "$VENV/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt" || exit 1
fi
exec "$VENV/bin/python" "$SCRIPT_DIR/digitone_preset_library.py"
