# Build script for Sims4ModTool using PyInstaller
# Usage: powershell -ExecutionPolicy Bypass -File .\build.ps1

param(
    [switch]$OneFile = $true,
    [switch]$NoConsole = $true,
    [string]$Name = "Sims4ModTool",
    [string]$Icon = ""
)

function Ensure-Python {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Error "Python not found in PATH"
        exit 1
    }
}

function Ensure-PyInstaller {
    # Check if PyInstaller is available via pip
    $null = & python -m pip show pyinstaller 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing PyInstaller..."
        & python -m pip install --user pyinstaller
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to install PyInstaller"
            exit 1
        }
    }
}

function Build-App {
    $opts = @()
    if ($OneFile) { $opts += "--onefile" }
    if ($NoConsole) { $opts += "--noconsole" }
    if ($Icon -and (Test-Path $Icon)) { $opts += @("--icon", $Icon) }
    $opts += @("--name", $Name)
    # Keep the build environment clean and avoid Qt binding conflicts
    $opts += "--clean"
    $opts += @("--exclude-module", "PySide6")
    $opts += @("--exclude-module", "PySide2")
    $opts += @("--exclude-module", "PyQt6")

    # Data files if needed (adjust as required)
    foreach ($data in @("version_release.json")) {
        if (Test-Path $data) {
            $opts += @("--add-data", "$data;.")
        }
    }

    $main = "main.py"
    if (-not (Test-Path $main)) { Write-Error "main.py not found"; exit 1 }

    Write-Host "Running PyInstaller..."
    python -m PyInstaller @opts $main
    if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed"; exit 1 }

    Write-Host "Build complete. See the 'dist' folder for output." -ForegroundColor Green
}

Ensure-Python
Ensure-PyInstaller
Build-App
