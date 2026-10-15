# BIGSTEN — Full authorized Roboflow picture pilot (Windows)
# The key exists ONLY in this PowerShell process and is never printed,
# committed, stored in dataset manifests or sent back to ChatGPT.
#
# Usage in a PowerShell terminal:
#   .\start-full-photo-benchmark.ps1 -Source detector
#   .\start-full-photo-benchmark.ps1 -Source binder
#   .\start-full-photo-benchmark.ps1 -Source scanner

param(
  [ValidateSet("detector","binder","scanner")]
  [string]$Source = "detector"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
  Write-Host "Optional local virtualenv missing." -ForegroundColor Yellow
  Write-Host "Run first:"
  Write-Host "  py -3 -m venv .venv"
  Write-Host "  .venv\Scripts\python.exe -m pip install -r requirements-local.txt"
  Write-Host "  .venv\Scripts\python.exe -m pip install roboflow"
  exit 1
}

Write-Host "BIGSTEN P1 - Official Roboflow dataset research" -ForegroundColor Cyan
Write-Host "Source: $Source"
Write-Host "Original images remain under gitignored private/roboflow-pilot."
Write-Host "Only card RECTANGLE metrics are produced, not exact card identities."
Write-Host "Provider access may require a Roboflow plan; do not bypass access."
Write-Host ""
Write-Host "Paste your authorized Roboflow API key (it will not be shown):"
$secret = Read-Host -AsSecureString
$pointer = [System.IntPtr]::Zero
try {
  $pointer = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
  $env:ROBOFLOW_API_KEY = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
  if ([string]::IsNullOrWhiteSpace($env:ROBOFLOW_API_KEY)) {
    throw "No API key entered"
  }
  & $python "run_roboflow_pilot.py" --source $Source --root ("private/roboflow-pilot-" + $Source)
  if ($LASTEXITCODE -ne 0) {
    throw "Roboflow export or benchmark failed. Check permission and dataset split."
  }
  Write-Host "Done. Open private/roboflow-pilot-$Source/reports/detection.html" -ForegroundColor Green
  Write-Host "Private source photos prepared for independent review."
}
finally {
  if ($pointer -ne [System.IntPtr]::Zero) {
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
  }
  Remove-Item Env:ROBOFLOW_API_KEY -ErrorAction SilentlyContinue
  $secret = $null
}
