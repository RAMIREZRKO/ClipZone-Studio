import json
import subprocess
from pathlib import Path

from ..config import Settings
from ..models import ClipRequest

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class MediaError(Exception):
    pass


class MediaService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def require(self, name: str) -> str:
        binary = self.settings.binary(name)
        if not binary:
            raise MediaError(f"No se encontró {name}. Ejecuta scripts/setup.ps1 -DownloadFFmpeg.")
        return binary

    def probe(self, path: Path) -> dict:
        try:
            result = subprocess.run(
                [self.require("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=CREATE_NO_WINDOW,
            )
            if result.returncode:
                raise MediaError("El archivo no es un vídeo válido o está dañado.")
            info = json.loads(result.stdout)
            stream = next((s for s in info["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")), None)
            if not stream:
                raise MediaError("El archivo no contiene una pista de vídeo.")
            duration = float(info["format"].get("duration") or stream.get("duration") or 0)
            if not 0 < duration < 7 * 24 * 3600:
                raise MediaError("No se pudo determinar una duración válida (máximo 7 días).")
            width, height = int(stream["width"]), int(stream["height"])
            rotation = int(float(stream.get("tags", {}).get("rotate", 0)))
            for side in stream.get("side_data_list", []):
                rotation = int(float(side.get("rotation", rotation)))
            if abs(rotation) % 180 == 90:
                width, height = height, width
            audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
            return {"duration": duration, "width": width, "height": height, "codec": stream["codec_name"], "pixel_format": stream.get("pix_fmt"),
                    "has_audio": audio is not None, "audio_codec": audio["codec_name"] if audio else None}
        except (subprocess.TimeoutExpired, ValueError, KeyError) as exc:
            raise MediaError("No se pudo leer la información del vídeo.") from exc

    def thumbnail(self, source: Path, target: Path):
        try:
            subprocess.run([self.require("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-protocol_whitelist", "file,pipe", "-ss", "0", "-i", str(source),
                            "-frames:v", "1", "-vf", "scale=480:-2", "-update", "1", str(target)],
                           capture_output=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            pass  # La miniatura es opcional; el vídeo sigue siendo editable.

    @staticmethod
    def video_filter(request: ClipRequest) -> str:
        w, h = request.dimensions()
        # Normaliza píxeles anamórficos antes de ajustar el encuadre.
        normalize = "scale=trunc(iw*sar/2)*2:ih,setsar=1"
        if request.fit == "cover":
            fit = (f"scale={w}:{h}:force_original_aspect_ratio=increase:force_divisible_by=2,"
                   f"crop={w}:{h}:(iw-ow)*{request.focus_x / 100}:(ih-oh)*{request.focus_y / 100}")
        else:
            fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
        return f"{normalize},{fit},setsar=1"

    def render_command(self, source: Path, output: Path, request: ClipRequest) -> list[str]:
        return [self.require("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-protocol_whitelist", "file,pipe", "-ss", str(request.start), "-i", str(source), "-t", str(request.end - request.start),
                "-map", "0:v:0", "-map", "0:a:0?", "-vf", self.video_filter(request),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-map_metadata", "-1",
                "-progress", "pipe:1", "-nostats", str(output)]

    def proxy_command(self, source: Path, output: Path) -> list[str]:
        return [self.require("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe", "-i", str(source),
                "-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=trunc(iw*sar/2)*2:ih,setsar=1,scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart", "-map_metadata", "-1", "-progress", "pipe:1", "-nostats", str(output)]
