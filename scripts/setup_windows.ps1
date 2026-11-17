<#
  Gutachten Assistant - one-time setup on Windows 11.

  Run from the repo root in PowerShell:
      powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1

  Installs (via winget, per-user where possible): uv, Tesseract OCR, Node.js LTS
  (only needed to build the UI). Then: Python deps, frontend build, models and
  the llama.cpp runtime matching the GPU driver. Safe to re-run.
  The app itself never goes online; only this setup downloads.
#>
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Ensure-Winget([string]$cmd, [string]$id, [string]$label) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        Write-Host "  ok      $label"
        return
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget not available - install '$label' manually (winget id: $id)."
    }
    Write-Host "  install $label ($id)"
    winget install --id $id -e --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget install $id failed ($LASTEXITCODE)" }
    Refresh-Path
}

Write-Host "== Prerequisites"
Ensure-Winget "uv" "astral-sh.uv" "uv (Python manager)"

# Tesseract's installer does not add itself to PATH; the app finds it in
# Program Files on its own, so only check the install location here.
$tess = @("$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
          "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
if ($tess -or (Get-Command tesseract -ErrorAction SilentlyContinue)) {
    Write-Host "  ok      Tesseract OCR"
} else {
    Ensure-Winget "tesseract" "UB-Mannheim.TesseractOCR" "Tesseract OCR"
}

Write-Host "== Python environment"
uv sync
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

Write-Host "== User interface"
if (Test-Path "web\dist\index.html") {
    Write-Host "  ok      web\dist already built"
} else {
    Ensure-Winget "npm" "OpenJS.NodeJS.LTS" "Node.js LTS"
    Push-Location web
    npm ci
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm ci failed" }
    npm run build
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm run build failed" }
    Pop-Location
}

Write-Host "== Models + llama.cpp runtime"
uv run python scripts\download_models.py
if ($LASTEXITCODE -ne 0) { throw "model download failed" }

Write-Host "== Check"
uv run python scripts\download_models.py --check
if ($LASTEXITCODE -ne 0) { throw "setup incomplete - see MISSING above" }

Write-Host ""
Write-Host "Setup complete. Start with: scripts\start_windows.bat"
Write-Host "Recommended: enable BitLocker on the drive holding the 'cases' folder."
