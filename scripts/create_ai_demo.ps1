# Audio sintetico local usando las voces de Windows. No requiere internet.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
Add-Type -AssemblyName System.Speech
New-Item -ItemType Directory -Path 'demo' -Force | Out-Null
$audioPath = Join-Path $projectRoot 'demo/phase2-spoken-demo.wav'
$videoPath = Join-Path $projectRoot 'demo/phase2-spoken-demo.mp4'
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $english = $speaker.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'en-*' } | Select-Object -First 1
    if ($english) { $speaker.SelectVoice($english.VoiceInfo.Name) }
    $speaker.Rate = 0
    $speaker.SetOutputToWaveFile($audioPath)
    $speaker.Speak('Do you know the secret to making a better video? Start with one clear idea. Show the most useful moment first. This simple change helps people understand your story. The biggest mistake is waiting too long to get to the point. Here is a practical tip. Remove the introduction and begin with the result. Every second should help explain your idea. How can you make your next video more interesting? Ask a question. Give a useful example. Finish with one clear action. That is how you turn a long conversation into a great short video.')
} finally { $speaker.Dispose() }
$ffmpegExe = Join-Path $projectRoot 'tools/ffmpeg/bin/ffmpeg.exe'
if ($env:CLIPZONE_FFMPEG) { $ffmpegExe = $env:CLIPZONE_FFMPEG }
elseif (-not (Test-Path -LiteralPath $ffmpegExe)) { $ffmpegExe = (Get-Command ffmpeg -ErrorAction Stop).Source }
& $ffmpegExe -hide_banner -loglevel error -y -f lavfi -i 'testsrc2=size=640x360:rate=24' -i $audioPath -shortest -c:v libx264 -preset veryfast -crf 25 -pix_fmt yuv420p -c:a aac -movflags +faststart $videoPath
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el video de prueba.' }
Write-Host ('Demo hablada: ' + $videoPath) -ForegroundColor Green
