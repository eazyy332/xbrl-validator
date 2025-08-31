Param(
  [string]$PythonExe = "python"
)

Write-Host "[build] Installing PyInstaller..."
& $PythonExe -m pip install --upgrade pip | Out-Host
& $PythonExe -m pip install pyinstaller | Out-Host

$spec = Join-Path (Get-Location) "packaging/pyinstaller_gui.spec"
if (!(Test-Path $spec)) {
  Write-Error "Spec not found: $spec"
  exit 2
}

Write-Host "[build] Running PyInstaller..."
& $PythonExe -m PyInstaller "$spec" --noconfirm | Out-Host

$dist = Join-Path (Get-Location) "dist/XBRLValidatorGUI"
if (Test-Path $dist) {
  Write-Host "[build] GUI bundled at: $dist"
} else {
  Write-Warning "dist folder not found; check PyInstaller output"
}
