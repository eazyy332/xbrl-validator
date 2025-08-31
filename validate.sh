#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"

exec "$PY" -m app.validate "$@"

