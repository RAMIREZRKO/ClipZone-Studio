param([switch]$Open, [switch]$Dev)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
$env:PYTHONUTF8 = '1'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Ejecuta primero .\scripts\setup.ps1 -DownloadFFmpeg.' }
$arguments = @('scripts/serve.py', '--check')
if ($Open) { $arguments += '--open' }
if ($Dev) { $arguments += '--dev' }
& $pythonExe @arguments
exit $LASTEXITCODE
