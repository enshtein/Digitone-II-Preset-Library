#!/bin/zsh
SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR" || exit 1
exec /usr/bin/env python3 "$SCRIPT_DIR/digitone_preset_library.py"
