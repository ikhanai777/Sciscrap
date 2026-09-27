#!/usr/bin/env bash
# Setup for WSL2 (Ubuntu) / Linux / macOS. Run from the repo folder:  bash scripts/setup_wsl.sh [--mcp]
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null; then
  echo "Installing python3..."; sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
fi
python3 -m venv .venv 2>/dev/null || { sudo apt-get install -y python3-venv && python3 -m venv .venv; }
.venv/bin/pip install --upgrade pip -q
if [[ "${1:-}" == "--mcp" ]]; then .venv/bin/pip install -e ".[mcp]" -q; else .venv/bin/pip install -e . -q; fi

# Put `sciscrap` on PATH for the terminal (and for Hermes Agent's terminal tool).
mkdir -p "$HOME/.local/bin"
ln -sf "$PWD/.venv/bin/sciscrap" "$HOME/.local/bin/sciscrap"
[[ -f .venv/bin/sciscrap-mcp ]] && ln -sf "$PWD/.venv/bin/sciscrap-mcp" "$HOME/.local/bin/sciscrap-mcp"

echo
echo "Installed: $(command -v sciscrap || echo "$HOME/.local/bin/sciscrap")"
echo "Test:  sciscrap search \"CRISPR gene editing\" -n 5"
