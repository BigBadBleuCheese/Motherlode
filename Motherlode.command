#!/bin/bash
cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
INSTALLER_URL="https://www.python.org/ftp/python/3.7.9/python-3.7.9-macosx10.9.pkg"

find_python() {
    local candidate
    for candidate in python3.7 \
            /Library/Frameworks/Python.framework/Versions/3.7/bin/python3.7 \
            /usr/local/bin/python3.7 \
            /opt/homebrew/bin/python3.7 \
            "$HOME"/.pyenv/versions/3.7*/bin/python3.7 \
            python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
                "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 7) else 1)' >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON="$(find_python)"
if [ -z "$PYTHON" ]; then
    echo "Motherlode needs Python 3.7, the version The Sims 4 uses, and it isn't installed."
    read -r -p "Download the official Python 3.7.9 installer from python.org now? [Y/n] " answer
    case "$answer" in
        [nN]*)
            echo "Install Python 3.7.9 from https://www.python.org/downloads/release/python-379/ and run Motherlode again."
            exit 1
            ;;
    esac
    PACKAGE="$HOME/Downloads/python-3.7.9-macosx10.9.pkg"
    if ! curl -fL --progress-bar -o "$PACKAGE" "$INSTALLER_URL"; then
        echo "The download failed. Install Python 3.7.9 from https://www.python.org/downloads/release/python-379/ and run Motherlode again."
        exit 1
    fi
    if ! pkgutil --check-signature "$PACKAGE" | grep -q "Python Software Foundation"; then
        echo "The installer isn't signed by the Python Software Foundation, so it won't be opened: $PACKAGE"
        exit 1
    fi
    open "$PACKAGE"
    echo "Finish the Python installer, then run Motherlode again."
    exit 0
fi

PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -m motherlode -o "$ROOT/decompiled" --open "$@"
