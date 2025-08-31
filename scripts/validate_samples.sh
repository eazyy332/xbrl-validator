#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
OUT_DIR="$ROOT_DIR/validation_output"
SAMPLES_DIRS=("$ROOT_DIR/samples" "$ROOT_DIR/test_data" "$ROOT_DIR/extra_data/sample_instances_architecture_1.0/xBRL_XML")

# Prefer project venv311 interpreter for Arelle compatibility
VENV_PY="$ROOT_DIR/.venv311/bin/python"
if [[ -x "$VENV_PY" ]]; then
  PY="$VENV_PY"
else
  PY="${PYTHON:-python3}"
fi

mkdir -p "$OUT_DIR"

found=0
for d in "${SAMPLES_DIRS[@]}"; do
  if [[ -d "$d" ]]; then
    found=1
    # Read null-delimited to handle spaces safely; validate up to 10 files per directory
    cnt=0
    while IFS= read -r -d '' f; do
      bn=$(basename "$f")
      echo "[INFO] Validating: $f"
      "$PY" -m app.validate \
        --file "$f" \
        --ebaVersion "3.5" \
        --cacheDir "$ROOT_DIR/assets/cache" \
        --out "$OUT_DIR/${bn}.jsonl" \
        --exports "$ROOT_DIR/exports/batch" \
        --formula run || true
      cnt=$((cnt+1))
      [[ $cnt -ge 10 ]] && break
    done < <(find "$d" -type f \( -name '*.xbrl' -o -name '*.xml' -o -name '*.xhtml' \) -print0)
  fi
done

if [[ $found -eq 0 ]]; then
  echo "[WARN] No samples directory found. Place XBRL files under samples/ or test_data/."
  exit 0
fi

echo "[OK] Sample validation run complete. Outputs under $OUT_DIR"


