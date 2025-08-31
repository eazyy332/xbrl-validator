Param(
  [switch]$Gui,
  [string]$Eba35Url = $env:EBA35_URL,
  [string]$Eba35Sha256 = $env:EBA35_SHA256,
  [string]$DpmZipUrl = $env:DPM_ZIP_URL,
  [string]$DpmSchema = "dpm35_20"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Info($m) { Write-Host "[info] $m" -ForegroundColor Cyan }
function Write-Warn($m) { Write-Host "[warn] $m" -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host "[error] $m" -ForegroundColor Red }

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Info "Project root: $Root"

# Paths
$VenvDir = Join-Path $Root ".venv"
$IsWin = $PSVersionTable.PSEdition -eq 'Desktop' -or $IsWindows
$PyExe = if ($IsWin) { Join-Path $VenvDir "Scripts/python.exe" } else { Join-Path $VenvDir "bin/python" }
$PipExe = if ($IsWin) { Join-Path $VenvDir "Scripts/pip.exe" } else { Join-Path $VenvDir "bin/pip" }
$LogsDir = Join-Path $Root "logs"
$ExportsDir = Join-Path $Root "exports"
$Tax35Dir = Join-Path $Root "assets/taxonomy/eba_3_5"
$Tax35Zip = Join-Path $Tax35Dir "EBA_3_5.zip"
$DpmSqlite = Join-Path $Root "assets/dpm.sqlite"
$DpmWork = Join-Path $Root "assets/work/dpm"
New-Item -ItemType Directory -Force -Path $LogsDir, $ExportsDir, $Tax35Dir, $DpmWork | Out-Null

# Check python on path for bootstrap
function Get-SystemPython {
  $candidates = @('python3', 'python')
  foreach ($c in $candidates) {
    $p = (Get-Command $c -ErrorAction SilentlyContinue)
    if ($p) { return $p.Path }
  }
  return $null
}

$SysPy = Get-SystemPython
if (-not $SysPy) { Write-Err "Python not found on PATH. Install Python 3.11+ first."; exit 1 }

# Verify version >= 3.11
$verOut = & $SysPy -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
Write-Info "System Python: $SysPy ($verOut)"
try {
  $maj,$min,$patch = $verOut.Split('.')
  if ([int]$maj -lt 3 -or ([int]$maj -eq 3 -and [int]$min -lt 11)) {
    Write-Err "Python 3.11+ required. Found $verOut"
    exit 1
  }
} catch { Write-Warn "Could not parse Python version. Continuing." }

# Ensure .venv writeable
if (Test-Path $VenvDir) {
  try {
    New-Item -ItemType Directory -Force -Path (Join-Path $VenvDir "_probe") | Out-Null
    Remove-Item -Recurse -Force (Join-Path $VenvDir "_probe")
  } catch { Write-Err "Cannot write to .venv folder: $VenvDir"; exit 1 }
}

# Create venv if missing
if (-not (Test-Path $PyExe)) {
  Write-Info "Creating virtual environment..."
  & $SysPy -m venv $VenvDir
}

# Upgrade pip and install deps
Write-Info "Upgrading pip/setuptools/wheel..."
& $PyExe -m pip install -U pip setuptools wheel | Write-Host

Write-Info "Installing project requirements..."
if (Test-Path (Join-Path $Root "requirements.txt")) {
  & $PipExe install -r (Join-Path $Root "requirements.txt") | Write-Host
} else {
  Write-Warn "requirements.txt not found; installing known runtime deps"
  & $PipExe install arelle-release rich requests openpyxl | Write-Host
}

# Ensure arelle available
Write-Info "Verifying Arelle import..."
& $PyExe -c "import arelle; import sys; print('arelle OK')" | Write-Host

# Ensure EBA 3.5 taxonomy present
function Get-FileSha256([string]$Path) {
  (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLower()
}

if (-not (Test-Path (Join-Path $Tax35Dir "taxonomyPackage.xml"))) {
  Write-Info "EBA 3.5 taxonomy not found; attempting download..."
  if (-not $Eba35Url) {
    Write-Warn "No EBA 3.5 URL provided. Set -Eba35Url or env:EBA35_URL. Using placeholder that will not work without update."
    $Eba35Url = "https://change-me/EBA_CRD_XBRL_3.5_Reporting_Frameworks_3.5.0.0.zip"
  }
  Write-Info "Downloading: $Eba35Url -> $Tax35Zip"
  try {
    Invoke-WebRequest -Uri $Eba35Url -OutFile $Tax35Zip -UseBasicParsing
  } catch {
    Write-Warn "Download failed: $_"
  }
  if (Test-Path $Tax35Zip) {
    if ($Eba35Sha256) {
      $actual = Get-FileSha256 $Tax35Zip
      if ($actual -ne $Eba35Sha256.ToLower()) {
        Write-Warn "SHA256 mismatch for EBA 3.5 zip. Expected $Eba35Sha256, got $actual"
      } else { Write-Info "SHA256 verified: $actual" }
    }
    Write-Info "Unzipping EBA 3.5 taxonomy..."
    try { Expand-Archive -Path $Tax35Zip -DestinationPath $Tax35Dir -Force } catch { Write-Warn "Unzip failed: $_" }
  }
}

# Build/Update DPM SQLite (optional; proceeds even if missing)
$dpmZipLocal = Get-ChildItem -Path $DpmWork -Filter *.zip -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $dpmZipLocal -and $DpmZipUrl) {
  $dpmZipLocal = Join-Path $DpmWork "dpm.zip"
  Write-Info "Downloading DPM zip: $DpmZipUrl -> $dpmZipLocal"
  try { Invoke-WebRequest -Uri $DpmZipUrl -OutFile $dpmZipLocal -UseBasicParsing } catch { Write-Warn "DPM download failed: $_" }
}
if ($dpmZipLocal) {
  Write-Info "Importing DPM into SQLite ($DpmSchema) ..."
  & $PyExe -m scripts.import_dpm_to_sqlite --zip "$($dpmZipLocal.FullName)" --sqlite "$DpmSqlite" --schema "$DpmSchema" | Write-Host
} else {
  Write-Warn "No DPM zip provided/found; skipping DPM import. Deterministic mapping will be limited."
}

# Samples
$Sample34 = Join-Path $Root "assets/work/samples/DUMMYLEI123456789012.CON_FR_COREP030200_COREPFRTB_2024-12-31_20240625002144000.xbrl"
if (-not (Test-Path $Sample34)) {
  Write-Warn "3.4 sample missing: $Sample34. Provide a valid instance to fully validate."
}

Write-Info "Running EBA 3.4 validation..."
$Log34 = Join-Path $LogsDir "eba34_run.jsonl"
& $PyExe -m app.validate --file "$Sample34" --ebaVersion 3.4 --out "$Log34" --plugins formula --exports "$ExportsDir" --dpm-sqlite "$DpmSqlite" --dpm-schema "$DpmSchema" --offline --cacheDir "assets/cache" | Write-Host

Write-Info "Running EBA 3.5 validation..."
$Log35 = Join-Path $LogsDir "eba35_run.jsonl"
& $PyExe -m app.validate --file "$Sample34" --ebaVersion 3.5 --out "$Log35" --plugins formula --exports "$ExportsDir" --dpm-sqlite "$DpmSqlite" --dpm-schema "$DpmSchema" --offline --cacheDir "assets/cache" | Write-Host

if ($Gui) {
  Write-Info "Launching GUI..."
  try {
    & $PyExe -m gui.xbrl_validator_app
  } catch {
    Write-Warn "GUI failed to start. If on macOS and _tkinter is missing, install Tk: brew install python-tk@3.11"
  }
}

Write-Host ""; Write-Info "Done. Outputs:"
Write-Host " - $Log34"
Write-Host " - $Log35"
Write-Host " - $ExportsDir (validation_messages.csv, results_by_file.json, formula_rollup.csv)"


