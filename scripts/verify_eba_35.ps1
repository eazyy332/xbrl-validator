Param(
  [string]$Instance = "",
  [string]$Out = "assets/logs/eba35_run.jsonl"
)

$ErrorActionPreference = "Stop"

$proj = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $proj

if (-not (Test-Path "config/taxonomy.json")) {
  Write-Error "Missing config/taxonomy.json"
}

if (-not (Test-Path ".venv")) {
  Write-Error "Missing .venv. Run tools/setup.sh first."
}

$python = ".venv/bin/python"
if (-not (Test-Path $python)) { $python = ".venv/Scripts/python.exe" }

$taxArg = "--ebaVersion 3.5"
if ($Instance -eq "") {
  # Fall back to first sample instance if not provided
  $samples = Get-ChildItem -Path "assets/work/samples" -Filter *.xbrl -ErrorAction SilentlyContinue
  if ($samples -and $samples.Length -gt 0) {
    $Instance = $samples[0].FullName
  } else {
    Write-Error "No sample .xbrl found under assets/work/samples. Provide -Instance or add samples."
  }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null

& $python -m app.validate --file "$Instance" --out "$Out" --plugins formula $taxArg | Write-Output

Write-Output "JSONL log: $Out"


