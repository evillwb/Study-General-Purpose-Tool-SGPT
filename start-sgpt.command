#!/usr/bin/env bash
# SGPT launcher for macOS and Linux: double-click (macOS) or run ./start-sgpt.command
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  rm -rf .venv  # left over from a setup that stopped
  echo "First run: setting up SGPT. This takes a few minutes..."
  python3 -m venv .venv && [ -x .venv/bin/python ] || { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt || exit 1
fi
exec .venv/bin/python -m sgpt.app "$@"
