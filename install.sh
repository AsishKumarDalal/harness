#!/usr/bin/env bash
# install.sh — set the harness up on a fresh machine.
#
#   git clone <repo> the-harness && cd the-harness && ./install.sh
#
# Creates the venv, installs the deps, and puts `harness` on your PATH.
# Safe to re-run: it only does what is missing.
set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO"

VENV="$REPO/.venv"
VPY="$VENV/bin/python"
USE_VENV=1

# 1. a python to work with ------------------------------------------------
PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
    echo "!! no python3 found — install python 3.11+ and retry" >&2
    exit 1
fi

# 2. the venv -------------------------------------------------------------
if [ -x "$VPY" ] && "$VPY" -c "import openai, dotenv" >/dev/null 2>&1; then
    echo "-> .venv already ready"
else
    echo "-> setting up .venv with $PY"
    if ! "$PY" -m venv "$VENV" >/dev/null 2>&1; then
        # Debian/Ubuntu without python3-venv: no ensurepip.
        # Build it without pip, then hand pip over.
        echo "   (ensurepip missing — bootstrapping pip another way)"
        rm -rf "$VENV"
        "$PY" -m venv --without-pip "$VENV" >/dev/null 2>&1
        if ! "$PY" -m pip --python "$VPY" install pip >/dev/null 2>&1; then
            curl -fsSL https://bootstrap.pypa.io/get-pip.py 2>/dev/null | "$VPY" >/dev/null 2>&1 || true
        fi
    fi

    if [ -x "$VPY" ] && "$VPY" -m pip --version >/dev/null 2>&1; then
        echo "-> installing dependencies into .venv"
        "$VPY" -m pip install --quiet --upgrade pip
        "$VPY" -m pip install --quiet -r "$REPO/requirements.txt"
    else
        # no venv possible -> run on the system python instead
        rm -rf "$VENV"
        USE_VENV=0
        echo "-> no venv possible — using the system python ($PY)"
        if ! "$PY" -m pip install --quiet --user -r "$REPO/requirements.txt"; then
            echo "!! could not install the dependencies. Try:" >&2
            echo "     $PY -m pip install --user -r $REPO/requirements.txt" >&2
            exit 1
        fi
    fi
fi

# 3. the `harness` command ------------------------------------------------
BIN_DIR="${HARNESS_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
chmod +x "$REPO/harness"
ln -sfn "$REPO/harness" "$BIN_DIR/harness"
echo "-> linked $BIN_DIR/harness -> $REPO/harness"

case ":$PATH:" in
    *":$BIN_DIR:"*) echo "-> $BIN_DIR is already on your PATH" ;;
    *) echo "!! $BIN_DIR is NOT on your PATH — add this to ~/.bashrc:"
       echo "     export PATH=\"\$PATH:$BIN_DIR\"" ;;
esac

# 4. settings -------------------------------------------------------------
if [ ! -f "$REPO/.env" ]; then
    cp "$REPO/.env.example" "$REPO/.env"
    echo "-> created .env from .env.example  (edit it: API key, BASE_URL, MODEL)"
else
    echo "-> .env already exists (left alone)"
fi

cat <<'EOF'

Ready. Open a NEW shell (or source ~/.bashrc), then:

    cd ~/projects/your-app
    harness

The harness' own state lives in ~/.harness — your project stays clean.
EOF
