#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ ! -d .venv ]]; then "$PYTHON_BIN" -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
if [[ "${INSIGHTFORGE_SKIP_INSTALL:-0}" != "1" ]]; then python -m pip install -e .; fi
exec python -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
