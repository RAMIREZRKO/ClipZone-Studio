param([ValidateSet('tiny', 'base', 'small')][string]$Model = 'base', [switch]$DependenciesOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
$env:PYTHONUTF8 = '1'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Instala primero el proyecto con scripts/setup.ps1 -DownloadFFmpeg.' }
Write-Host 'Instalando Whisper local y PyTorch (CPU). La descarga puede ocupar varios cientos de MB.' -ForegroundColor Green
& $pythonExe -m pip install -r backend/requirements-ai.txt -c backend/requirements-ai.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'No se pudo instalar Whisper. Revisa la conexion y tu version de Python.' }
if (-not $DependenciesOnly) {
    & $pythonExe scripts/download_model.py --model $Model
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo descargar o verificar el modelo.' }
}
& $pythonExe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Hay dependencias incompatibles.' }
Write-Host 'Abre Momentos con IA para elegir un modelo instalado o instalar otro.' -ForegroundColor Green
