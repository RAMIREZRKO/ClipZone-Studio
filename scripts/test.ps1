$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Path (Join-Path $projectRoot 'test-results') -Force | Out-Null
Push-Location -LiteralPath (Join-Path $projectRoot 'backend')
try {
    $testRun = Join-Path $projectRoot ('test-results/pytest-' + [guid]::NewGuid().ToString('N'))
    & $pythonExe -m pytest -q --basetemp=$testRun
    if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas del backend.' }
} finally { Pop-Location }
