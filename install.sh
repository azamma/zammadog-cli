#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing zammadog from $REPO_DIR..."

if command -v uv &>/dev/null; then
    uv pip install -e "$REPO_DIR"
elif command -v pip &>/dev/null; then
    pip install -e "$REPO_DIR"
elif command -v pip3 &>/dev/null; then
    pip3 install -e "$REPO_DIR"
else
    echo "Error: no pip or uv found. Install one first:" >&2
    echo "  pip:  https://pip.pypa.io" >&2
    echo "  uv:   curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

echo ""
echo "Verifying..."
zammadog --version

echo ""
echo "Done. Set credentials before use:"
echo "  export DD_API_KEY=..."
echo "  export DD_APP_KEY=..."
echo "  export DD_SITE=datadoghq.com"
