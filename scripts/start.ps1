param([switch]$Open, [switch]$Dev)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
$env:PYTHONUTF8 = '1'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Ejecuta primero .\scripts\setup.ps1 -DownloadFFmpeg.' }
& $pythonExe scripts/doctor.py
if ($LASTEXITCODE -ne 0) { throw 'Corrige las dependencias indicadas antes de iniciar.' }
if (-not $Dev -and -not (Test-Path -LiteralPath 'frontend/dist/index.html')) { throw 'Compila el editor: cd frontend; npm ci; npm run build.' }
Write-Host 'ClipZone Studio: http://127.0.0.1:8000' -ForegroundColor Green
Write-Host 'API: http://127.0.0.1:8000/docs | Ctrl+C para cerrar.'
if ($Dev) { Write-Host 'Modo desarrollo: en otra terminal ejecuta cd frontend y npm run dev (puerto 5173).' }
$arguments = @('scripts/serve.py')
if ($Open) { $arguments += '--open' }
if ($Dev) { $arguments += '--dev' }
& $pythonExe @arguments
if ($LASTEXITCODE -ne 0) { throw 'El servidor se cerro con error. Revisa si el puerto 8000 ya esta ocupado.' }
