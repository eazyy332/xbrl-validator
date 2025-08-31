## Packaging

Build GUI app (macOS/Windows):

```bash
pip install pyinstaller
pyinstaller packaging/pyinstaller_gui.spec --noconfirm
```

Artifacts will be in `dist/XBRLValidatorGUI/`.

CI runs acceptance (core + filing) on macOS and Windows. To run locally:

```bash
python -m scripts.cache_prime
python -m scripts.gen_table_aliases
python -m scripts.acceptance --mode core
python -m scripts.acceptance --mode filing --expect-csv --expect-json config/expected_curated.json
```

# XBRL Validation Tool (Arelle-based)

Professional XBRL validator built on Arelle with full EBA taxonomy support, deterministic DPM mapping, and comprehensive reporting. Supports XBRL 2.1, iXBRL, OIM (CSV/JSON), and regulatory frameworks. Designed for real validation without mock data.

#### Quick start

1) Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

2) **FIXED**: The main validation tool is now working! Use the convenient wrapper script:

```bash
# Make the wrapper executable
chmod +x validate.sh

# Run validation
./validate.sh --file /path/to/instance.xbrl --out validation.jsonl

# With EBA taxonomy version
./validate.sh --file /path/to/instance.xbrl --ebaVersion 3.5 --out validation.jsonl
```

Or run directly with Python:

```bash
# Using virtual environment
./.venv/bin/python app/validate.py --file /path/to/instance.xbrl --out validation.jsonl

# The import path issue has been fixed by adding the project root to sys.path
```

Notes:
- Use `--packages` to load an XBRL taxonomy package ZIP (e.g., EBA). You may also use the `zip#entry.xsd` syntax if you want to point to a specific entry point inside the package.
- Pass extra Arelle arguments via `--arelle "--someFlag --anotherFlag"`.

3) Run the GUI:

```
./.venv/bin/python -m gui.xbrl_validator_app
```

4) Download a taxonomy package (optional helper):

```
./.venv/bin/python scripts/download_eba_taxonomy.py \
  --url https://example.com/eba-taxonomy.zip \
  --out assets/eba-taxonomy.zip
```

#### Examples

Validate with package ZIP:

```
./.venv/bin/python -m xbrl_validator.cli \
  --file ./samples/instance.xbrl \
  --packages ./assets/eba-taxonomy.zip \
  --validate
```

Validate with `zip#entry.xsd`:

```
./.venv/bin/python -m xbrl_validator.cli \
  --file ./samples/instance.xbrl \
  --packages ./assets/eba-taxonomy.zip#path/inside/zip/entry-point.xsd \
  --validate
```

#### Notes

- This tool shells out to `arelle.CntlrCmdLine` to ensure compatibility with upstream Arelle options.
- For EBA, always load the full taxonomy package via `--packages` or `zip#entry.xsd`.
- No mock data is included; bring your real instance files and taxonomy packages.

#### JSONL Runner and EBA stacks

End-to-end JSONL logging with formula plugin enabled and taxonomy stacks via `config/taxonomy.json`:

```bash
# EBA 3.5 validation with full offline support
python -m app.validate \
  --file instance.xbrl \
  --ebaVersion 3.5 \
  --out validation.jsonl \
  --exports exports/ \
  --offline \
  --severity-exit ERROR \
  --out-junit exports/junit.xml \
  --out-html exports/report.html

# iXBRL validation
python -m app.validate \
  --file report.xhtml \
  --out ixbrl.jsonl \
  --calcDecimals

# OIM JSON validation  
python -m app.validate \
  --file data.json \
  --out oim.jsonl

# Batch processing with process pool
python -m app.validate \
  --dir /path/to/instances/ \
  --ebaVersion 3.5 \
  --out batch.jsonl \
  --jobs 4

# Diff against baseline
python -m app.validate \
  --file instance.xbrl \
  --ebaVersion 3.5 \
  --out current.jsonl \
  --baseline previous.jsonl \
  --diff-out changes.json
```

## API Usage

Start the REST API server:
```bash
python -m api.server
# or with uvicorn: uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Submit validation jobs:
```bash
curl -X POST "http://localhost:8000/validate" \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "/path/to/instance.xbrl",
    "eba_version": "3.5",
    "severity_exit": "ERROR",
    "calc_decimals": true
  }'

# Check job status
curl "http://localhost:8000/jobs/{job_id}"

# Get validation log
curl "http://localhost:8000/jobs/{job_id}/log"
```

## CI Integration

```yaml
# GitHub Actions example
- name: XBRL Validation
  run: |
    python -m app.validate \
      --file ${{ matrix.instance }} \
      --ebaVersion 3.5 \
      --out validation.jsonl \
      --severity-exit ERROR \
      --out-junit results.xml
      
- name: Upload results
  uses: actions/upload-artifact@v3
  with:
    name: xbrl-validation-results
    path: |
      validation.jsonl
      results.xml
      exports/
```

## Docker

```bash
# Build image
docker build -t xbrl-validator .

# Run API server
docker run -p 8000:8000 xbrl-validator

# Run CLI validation
docker run -v /path/to/files:/data xbrl-validator \
  python -m app.validate --file /data/instance.xbrl --out /data/results.jsonl
```

## Testing & Conformance

Run conformance suites:
```bash
python scripts/run_conformance.py --suites xbrl-2.1 formula oim-csv
```

Run unit tests:
```bash
pytest tests/ -v
```

GUI also supports selecting EBA version (3.4/3.5) and validating samples.

