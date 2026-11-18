"""Genera un vídeo sintético con audio, sin descargar contenido de terceros."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings

target = ROOT / "demo" / "clipzone-demo.mp4"
target.parent.mkdir(parents=True, exist_ok=True)
ffmpeg = Settings().binary("ffmpeg")
if not ffmpeg:
    raise SystemExit("Falta FFmpeg. Ejecuta scripts/setup.ps1 -DownloadFFmpeg.")
subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000", "-t", "12", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(target)], check=True)
print(target)
