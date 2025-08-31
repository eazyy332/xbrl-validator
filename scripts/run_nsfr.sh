#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/omarfrix/Desktop/untitled folder 12"
VENV="$ROOT/.venv/bin/activate"
INSTANCE="$ROOT/assets/work/tmp/localized_NSFR_IND.xbrl"
OUT_DIR="$ROOT/exports/acceptance/proof_nsfr"
LOG="$ROOT/assets/logs/nsfr_3_4.log"

if [[ ! -f "$INSTANCE" ]]; then
  echo "Instance not found: $INSTANCE" >&2
  exit 1
fi

if [[ -f "$VENV" ]]; then
  # shellcheck disable=SC1090
  source "$VENV"
fi

cd "$ROOT"
mkdir -p "$OUT_DIR" "$(dirname "$LOG")"

python3 -m app.validate \
  --file "$INSTANCE" \
  --ebaVersion 3.4 \
  --out "$OUT_DIR/run.jsonl" \
  --plugins formula \
  --formulas \
  --offline \
  --cacheDir "$ROOT/assets/cache" \
  --exports "$OUT_DIR" \
  --dpm-sqlite "$ROOT/assets/dpm.sqlite" \
  --dpm-schema dpm35_10 \
  --arelleArgs "--logLevel info --logFormat message --logFile $LOG"

echo "Log written to: $LOG"
echo "Exports written to: $OUT_DIR"


