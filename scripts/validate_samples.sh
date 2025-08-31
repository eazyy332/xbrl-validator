#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
OUT_DIR="$ROOT_DIR/validation_output"
SAMPLES_DIRS=("$ROOT_DIR/samples" "$ROOT_DIR/test_data")

mkdir -p "$OUT_DIR"

found=0
for d in "${SAMPLES_DIRS[@]}"; do
  if [[ -d "$d" ]]; then
    found=1
    for f in $(find "$d" -type f \( -name '*.xbrl' -o -name '*.xml' -o -name '*.xhtml' \) | head -n 10); do
      bn=$(basename "$f")
      echo "[INFO] Validating: $f"
      "$ROOT_DIR/validate.sh" --file "$f" --out "$OUT_DIR/${bn}.jsonl" --plugins formula --exports "$ROOT_DIR/exports" || true
    done
  fi
done

if [[ $found -eq 0 ]]; then
  echo "[WARN] No samples directory found. Place XBRL files under samples/ or test_data/."
  exit 0
fi

echo "[OK] Sample validation run complete. Outputs under $OUT_DIR"

