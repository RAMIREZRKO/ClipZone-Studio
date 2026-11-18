param([string]$Python = '', [switch]$DownloadFFmpeg, [switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'

function Assert-Exit([string]$Message) { if ($LASTEXITCODE -ne 0) { throw $Message } }

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Instala Node.js LTS (22.12+ o 24+) y vuelve a abrir PowerShell.' }
$nodeVersion = (& node -p 'process.versions.node').Split('.')
$major = [int]$nodeVersion[0]; $minor = [int]$nodeVersion[1]
if (($major -eq 20 -and $minor -lt 19) -or ($major -eq 22 -and $minor -lt 12) -or $major -lt 20 -or $major -eq 21) { throw 'Vite requiere Node 20.19+, 22.12+ o una LTS posterior.' }

if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    if (-not $Python) {
        $candidates = @('python', 'python3', 'py', (Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'))
        foreach ($candidate in $candidates) {
            $command = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($command -and $command.Source -notlike '*WindowsApps*') { $Python = $command.Source; break }
        }
    }
    if (-not $Python) { throw 'Instala Python 3.12 desde python.org. Tambien puedes indicar -Python C:\ruta\python.exe.' }
    & $Python -m venv .venv
    Assert-Exit 'No se pudo crear el entorno Python.'
}
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
& $pythonExe -c 'import sys; assert sys.version_info >= (3, 10), "Se requiere Python 3.10+; recomendado 3.12"'
Assert-Exit 'Version de Python incompatible.'
Write-Host '[1/5] Instalando backend...' -ForegroundColor Green
& $pythonExe -m pip install -r backend/requirements-dev.txt -c backend/requirements.lock.txt
Assert-Exit 'Fallo al instalar las dependencias Python.'

if ($DownloadFFmpeg -and (-not (Test-Path -LiteralPath 'tools/ffmpeg/bin/ffmpeg.exe') -or -not (Test-Path -LiteralPath 'tools/ffmpeg/bin/ffprobe.exe'))) {
    Write-Host '[2/5] Descargando FFmpeg y FFprobe para Windows x64...' -ForegroundColor Green
    New-Item -ItemType Directory -Path 'tools/ffmpeg/bin' -Force | Out-Null
    $archivePath = Join-Path $projectRoot 'tools/ffmpeg-release-essentials.zip'
    Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $archivePath -UseBasicParsing
    Expand-Archive -LiteralPath $archivePath -DestinationPath 'tools/ffmpeg-download' -Force
    $downloadFolder = Get-ChildItem -LiteralPath 'tools/ffmpeg-download' -Directory | Select-Object -First 1
    Copy-Item -LiteralPath (Join-Path $downloadFolder.FullName 'bin/ffmpeg.exe'),(Join-Path $downloadFolder.FullName 'bin/ffprobe.exe') -Destination 'tools/ffmpeg/bin' -Force
    # Conserva tambien la licencia e informacion del distribuidor del binario.
    Get-ChildItem -LiteralPath $downloadFolder.FullName -File | Copy-Item -Destination 'tools/ffmpeg' -Force
    Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
}
Write-Host '[3/5] Instalando y compilando React...' -ForegroundColor Green
Push-Location -LiteralPath 'frontend'
try {
    & npm.cmd ci --no-audit --no-fund
    Assert-Exit 'Fallo npm ci.'
    & npm.cmd run build
    Assert-Exit 'Fallo la compilacion del editor.'
} finally { Pop-Location }
Write-Host '[4/5] Comprobando dependencias...' -ForegroundColor Green
& $pythonExe scripts/doctor.py
Assert-Exit 'Faltan dependencias. Usa -DownloadFFmpeg o configura CLIPZONE_FFMPEG y CLIPZONE_FFPROBE.'
if (-not $SkipTests) {
    Write-Host '[5/5] Ejecutando pruebas de video...' -ForegroundColor Green
    & $PSScriptRoot/test.ps1
}
Write-Host 'Listo. Ejecuta .\scripts\start.ps1 -Open, o abre Iniciar ClipZone.cmd.' -ForegroundColor Green
