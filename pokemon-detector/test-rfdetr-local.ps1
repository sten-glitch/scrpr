param([string]$Dataset, [string]$Checkpoint, [switch]$RequireCuda)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $PythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        throw 'Create .venv and install requirements-rfdetr.txt plus rfdetr[train]==1.11.2 first.'
    }
    & $PythonExe -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
    & $PythonExe -m unittest discover -s tests -p 'test_*rfdetr*.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'RF-DETR regression tests failed.' }
    $PreflightArgs = @('check_rfdetr_local.py')
    if ($Dataset) { $PreflightArgs += @('--dataset', $Dataset) }
    if ($Checkpoint) { $PreflightArgs += @('--checkpoint', $Checkpoint) }
    if ($RequireCuda) { $PreflightArgs += '--require-cuda' }
    & $PythonExe @PreflightArgs
    if ($LASTEXITCODE -ne 0) { throw 'Local preflight failed; inspect private/rfdetr-preflight.json.' }
} finally {
    Pop-Location
}
