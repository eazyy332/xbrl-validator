#!/usr/bin/env bash
set -euo pipefail

# Setup EBA taxonomy packages under assets/taxonomies with checksums.
# Usage:
#   scripts/setup_taxonomies.sh --version 3.5 [--url <zip_url>] [--out-dir <dir>]
#
# Notes:
# - If --url is omitted, the script reads config/taxonomy_sources.json to find the URL.
# - If an interactive download or license acceptance is required, the script prints manual steps.

ROOT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
OUT_DIR="$ROOT_DIR/assets/taxonomies/EBA"
VERSION="3.5"
URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2;;
    --url) URL="$2"; shift 2;;
    --out-dir) OUT_DIR="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

mkdir -p "$OUT_DIR/$VERSION"
CHECKSUMS="$OUT_DIR/checksums.txt"
TMP_ZIP="$(mktemp -t eba-taxonomy.XXXXXX).zip"

if [[ -z "$URL" ]]; then
  SRC_JSON="$ROOT_DIR/config/taxonomy_sources.json"
  if [[ -f "$SRC_JSON" ]]; then
    URL=$(python3 - <<PY
import json,sys
from pathlib import Path
p=Path("$SRC_JSON")
d=json.loads(p.read_text(encoding='utf-8'))
u=d.get('sources',{}).get('EBA',{}).get('versions',{}).get('$VERSION',{}).get('packages',[{}])[0].get('url','')
print(u)
PY
)
  fi
fi

if [[ -z "$URL" || "$URL" == *"<INSERT_OFFICIAL"* ]]; then
  echo "[INFO] No URL configured for EBA $VERSION."
  echo "Please edit config/taxonomy_sources.json with the official zip URL for EBA $VERSION."
  echo "Alternatively, pass --url <zip_url> to this script."
  exit 2
fi

echo "[INFO] Downloading EBA $VERSION package: $URL"
set +e
curl -fL --retry 5 --retry-delay 2 --retry-connrefused -o "$TMP_ZIP" "$URL"
RC=$?
set -e
if [[ $RC -ne 0 ]]; then
  echo "[ERROR] Download failed (curl exit $RC). If a manual download is required, retrieve the zip and place it at:"
  echo "  $OUT_DIR/$VERSION/eba-taxonomy-$VERSION.zip"
  echo "Then re-run this script to compute checksums."
  exit $RC
fi

TARGET="$OUT_DIR/$VERSION/$(basename "$TMP_ZIP")"
mv "$TMP_ZIP" "$TARGET"
echo "[INFO] Saved to $TARGET"

if command -v sha256sum >/dev/null 2>&1; then
  SHA=$(sha256sum "$TARGET" | awk '{print $1}')
else
  # macOS fallback
  SHA=$(shasum -a 256 "$TARGET" | awk '{print $1}')
fi
echo "EBA $VERSION  $(basename "$TARGET")  sha256=$SHA" >> "$CHECKSUMS"
echo "[INFO] Recorded checksum in $CHECKSUMS"

echo "[OK] EBA taxonomy package ready at $TARGET"


