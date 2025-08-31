#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

python3 -m venv .venv
"${PROJECT_ROOT}/.venv/bin/pip" install --upgrade pip
"${PROJECT_ROOT}/.venv/bin/pip" install -r requirements.txt

# Auto-download EBA taxonomy assets if missing
ASSETS_DIR="${PROJECT_ROOT}/assets"
WORK_DIR="${ASSETS_DIR}/work"
mkdir -p "${ASSETS_DIR}" "${WORK_DIR}"

TAXONOMY_BUNDLE_URL="https://www.eba.europa.eu/sites/default/files/2024-02/53849087-9f8d-4b68-93e9-0b27e1092b36/taxo_package.zip"
TAXONOMY_BUNDLE_ZIP="${ASSETS_DIR}/eba-taxonomy-package.zip"

FULL_TAXONOMY_URL="https://www.eba.europa.eu/sites/default/files/2024-07/074ba246-f2a8-4169-bf79-78cd62677975/full_taxonomy_and_support_documents.zip"
FULL_TAXONOMY_ZIP="${ASSETS_DIR}/eba-taxonomy.zip"

SAMPLES_URL="https://www.eba.europa.eu/sites/default/files/2024-07/099a5662-9e46-420e-8350-2979be3c02a6/sample_instances_architecture_2.0.zip"
SAMPLES_ZIP="${ASSETS_DIR}/eba-samples.zip"

if [ ! -f "${TAXONOMY_BUNDLE_ZIP}" ]; then
  echo "Downloading EBA taxonomy package bundle..."
  "${PROJECT_ROOT}/.venv/bin/python" scripts/download_eba_taxonomy.py --url "${TAXONOMY_BUNDLE_URL}" --out "${TAXONOMY_BUNDLE_ZIP}"
fi

if [ ! -f "${FULL_TAXONOMY_ZIP}" ]; then
  echo "Downloading EBA full taxonomy and support documents..."
  "${PROJECT_ROOT}/.venv/bin/python" scripts/download_eba_taxonomy.py --url "${FULL_TAXONOMY_URL}" --out "${FULL_TAXONOMY_ZIP}"
fi

if [ ! -f "${SAMPLES_ZIP}" ]; then
  echo "Downloading EBA sample instances..."
  "${PROJECT_ROOT}/.venv/bin/python" scripts/download_eba_taxonomy.py --url "${SAMPLES_URL}" --out "${SAMPLES_ZIP}"
fi

echo "Unpacking EBA taxonomy package bundle..."
mkdir -p "${WORK_DIR}/eba-package"
unzip -o "${TAXONOMY_BUNDLE_ZIP}" -d "${WORK_DIR}/eba-package" > /dev/null

echo "Unpacking sample instances..."
mkdir -p "${WORK_DIR}/samples"
unzip -o "${SAMPLES_ZIP}" -d "${WORK_DIR}/samples" > /dev/null

DEFAULT_PACKAGE_ZIP="${WORK_DIR}/eba-package/EBA_CRD_XBRL_3.4_Reporting_Frameworks_3.4.0.0.zip"
DEFAULT_INSTANCE_FILE=$(ls "${WORK_DIR}/samples"/*.xbrl 2>/dev/null | head -n 1 || true)

# DPM databases (3.5): DPM 2.0 and DPM 1.0
DPM20_URL="https://www.eba.europa.eu/sites/default/files/2024-07/39caec2e-4ede-4418-91c5-1190e03b9034/dpm_databse_3.5_dpm_2.0.zip"
DPM10_URL="https://www.eba.europa.eu/sites/default/files/2024-07/872b1b27-696b-47ec-abe6-48244c3e6575/dpm_databse_3.5_dpm_1.0.zip"
DPM20_ZIP="${ASSETS_DIR}/dpm35_20.zip"
DPM10_ZIP="${ASSETS_DIR}/dpm35_10.zip"
if [ ! -f "${DPM20_ZIP}" ]; then
  echo "Downloading DPM 3.5 (DPM 2.0) ..."
  "${PROJECT_ROOT}/.venv/bin/python" scripts/download_eba_taxonomy.py --url "${DPM20_URL}" --out "${DPM20_ZIP}"
fi
if [ ! -f "${DPM10_ZIP}" ]; then
  echo "Downloading DPM 3.5 (DPM 1.0) ..."
  "${PROJECT_ROOT}/.venv/bin/python" scripts/download_eba_taxonomy.py --url "${DPM10_URL}" --out "${DPM10_ZIP}"
fi

# Build SQLite from DPM packages
SQLITE_PATH="${ASSETS_DIR}/dpm.sqlite"
echo "Importing DPM 3.5 (DPM 2.0) into SQLite..."
"${PROJECT_ROOT}/.venv/bin/python" scripts/import_dpm_to_sqlite.py --zip "${DPM20_ZIP}" --sqlite "${SQLITE_PATH}" --schema dpm35_20 || true
echo "Importing DPM 3.5 (DPM 1.0) into SQLite..."
"${PROJECT_ROOT}/.venv/bin/python" scripts/import_dpm_to_sqlite.py --zip "${DPM10_ZIP}" --sqlite "${SQLITE_PATH}" --schema dpm35_10 || true

echo ""
echo "Setup complete. Activate venv: source .venv/bin/activate"
echo "Run CLI (example):"
echo "  python -m xbrl_validator.cli \\
    --file \"${DEFAULT_INSTANCE_FILE:-/path/to/instance.xbrl}\" \\
    --packages \"${DEFAULT_PACKAGE_ZIP}\" \\
    --arelle \"--validate --calcDecimals\""
echo "Run GUI: python -m gui.xbrl_validator_app"

