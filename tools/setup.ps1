Param(
    [string]$TaxonomyUrl = "",
    [string]$TaxonomyOut = "assets/eba-taxonomy.zip",
    [string]$Sha256 = "",
    [switch]$RunGui
)

$ErrorActionPreference = "Stop"

Push-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location ..

if (!(Test-Path .venv)) {
    py -3 -m venv .venv
}
& .\.venv\Scripts\pip.exe install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements.txt

# Auto-download EBA assets if no explicit URL is provided
$assetsDir = "assets"
$workDir = Join-Path $assetsDir "work"
New-Item -ItemType Directory -Force -Path $assetsDir | Out-Null
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

if ($TaxonomyUrl -ne "") {
    & .\.venv\Scripts\python.exe scripts\download_eba_taxonomy.py --url $TaxonomyUrl --out $TaxonomyOut $(if ($Sha256 -ne "") {"--sha256 $Sha256"})
}
else {
    $bundleUrl = "https://www.eba.europa.eu/sites/default/files/2024-02/53849087-9f8d-4b68-93e9-0b27e1092b36/taxo_package.zip"
    $bundleZip = Join-Path $assetsDir "eba-taxonomy-package.zip"
    if (-not (Test-Path $bundleZip)) {
        Write-Host "Downloading EBA taxonomy package bundle..."
        & .\.venv\Scripts\python.exe scripts\download_eba_taxonomy.py --url $bundleUrl --out $bundleZip
    }
    $fullTaxUrl = "https://www.eba.europa.eu/sites/default/files/2024-07/074ba246-f2a8-4169-bf79-78cd62677975/full_taxonomy_and_support_documents.zip"
    $fullTaxZip = Join-Path $assetsDir "eba-taxonomy.zip"
    if (-not (Test-Path $fullTaxZip)) {
        Write-Host "Downloading EBA full taxonomy and support documents..."
        & .\.venv\Scripts\python.exe scripts\download_eba_taxonomy.py --url $fullTaxUrl --out $fullTaxZip
    }
    $samplesUrl = "https://www.eba.europa.eu/sites/default/files/2024-07/099a5662-9e46-420e-8350-2979be3c02a6/sample_instances_architecture_2.0.zip"
    $samplesZip = Join-Path $assetsDir "eba-samples.zip"
    if (-not (Test-Path $samplesZip)) {
        Write-Host "Downloading EBA sample instances..."
        & .\.venv\Scripts\python.exe scripts\download_eba_taxonomy.py --url $samplesUrl --out $samplesZip
    }

    Write-Host "Unpacking EBA taxonomy bundle and samples..."
    $pkgDir = Join-Path $workDir "eba-package"
    $samplesDir = Join-Path $workDir "samples"
    New-Item -ItemType Directory -Force -Path $pkgDir | Out-Null
    New-Item -ItemType Directory -Force -Path $samplesDir | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($bundleZip, $pkgDir, $true)
    [System.IO.Compression.ZipFile]::ExtractToDirectory($samplesZip, $samplesDir, $true)

    # DPM 3.5 packages
    $dpm20Url = "https://www.eba.europa.eu/sites/default/files/2024-07/39caec2e-4ede-4418-91c5-1190e03b9034/dpm_databse_3.5_dpm_2.0.zip"
    $dpm10Url = "https://www.eba.europa.eu/sites/default/files/2024-07/872b1b27-696b-47ec-abe6-48244c3e6575/dpm_databse_3.5_dpm_1.0.zip"
    $dpm20Zip = Join-Path $assetsDir "dpm35_20.zip"
    $dpm10Zip = Join-Path $assetsDir "dpm35_10.zip"
    if (-not (Test-Path $dpm20Zip)) {
        Write-Host "Downloading DPM 3.5 (DPM 2.0)..."
        & .\.venv\Scripts\python.exe scripts\download_eba_taxonomy.py --url $dpm20Url --out $dpm20Zip
    }
    if (-not (Test-Path $dpm10Zip)) {
        Write-Host "Downloading DPM 3.5 (DPM 1.0)..."
        & .\.venv\Scripts\python.exe scripts\download_eba_taxonomy.py --url $dpm10Url --out $dpm10Zip
    }

    # Build SQLite
    $sqlitePath = Join-Path $assetsDir "dpm.sqlite"
    Write-Host "Importing DPM 3.5 (DPM 2.0) into SQLite..."
    & .\.venv\Scripts\python.exe scripts\import_dpm_to_sqlite.py --zip $dpm20Zip --sqlite $sqlitePath --schema dpm35_20
    Write-Host "Importing DPM 3.5 (DPM 1.0) into SQLite..."
    & .\.venv\Scripts\python.exe scripts\import_dpm_to_sqlite.py --zip $dpm10Zip --sqlite $sqlitePath --schema dpm35_10
}

if ($RunGui) {
    & .\.venv\Scripts\python.exe -m gui.xbrl_validator_app
}

Pop-Location
Pop-Location

