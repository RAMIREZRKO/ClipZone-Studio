import json
import subprocess
from pathlib import Path

from ..config import Settings
from ..composition import GraphicLayer
from ..models import ClipRequest
from ..split_layout import EMPTY_GAMEPLAY, SourceGeometry, split_geometry, split_graph

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
            sar_width, _, sar_height = stream.get("sample_aspect_ratio", "").partition(":")
            numerator, denominator = (int(sar_width), int(sar_height)) if sar_width.isdecimal() and sar_height.isdecimal() else (1, 1)
            if not numerator or not denominator:
                numerator, denominator = 1, 1
            rotation = int(float(stream.get("tags", {}).get("rotate", 0)))
            for side in stream.get("side_data_list", []):
                rotation = int(float(side.get("rotation", rotation)))
            if abs(rotation) % 180 == 90:
                width, height = height, width
                numerator, denominator = denominator, numerator
            display_width = max(2, 2 * (width * numerator // (2 * denominator)))
            audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
            return {"duration": duration, "width": width, "height": height, "display_width": display_width,
                    "codec": stream["codec_name"], "pixel_format": stream.get("pix_fmt"),
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

    def source_geometry(self, path: Path, metadata: dict | None = None) -> SourceGeometry:
        if not metadata or not metadata.get("display_width"):
            metadata = self.probe(path)
        return SourceGeometry(width=metadata["width"], height=metadata["height"], display_width=metadata["display_width"])

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

    def render_command(self, source: Path, output: Path, request: ClipRequest, *, use_ass: bool = False,
                       layers: list[tuple[GraphicLayer, Path | str]] | None = None,
                       source_geometry: SourceGeometry | None = None) -> list[str]:
        if request.fit == "split" and request.split_layout:
            geometry = split_geometry(request.split_layout, request.dimensions(), source_geometry or self.source_geometry(source))
            if geometry is None:
                raise MediaError(EMPTY_GAMEPLAY)
            graph = split_graph(request.split_layout, geometry)
        elif request.fit == "blur":
            w, h = request.dimensions()
            # Both layers come from the same decoded frame, including rotation and SAR.
            sigma = max(.01, request.blur_strength / 100 * min(w, h) * .055)
            scale = f"scale={w}:{h}:force_divisible_by=2:force_original_aspect_ratio"
            graph = (
                "[0:V:0]scale=trunc(iw*sar/2)*2:ih,setsar=1,split[background][foreground];"
                f"[background]{scale}=increase,crop={w}:{h},gblur=sigma={sigma:.4f}:steps=2[blur];"
                f"[foreground]{scale}=decrease[fit];"
                "[blur][fit]overlay=(W-w)/2:(H-h)/2:shortest=1,setsar=1[video]"
            )
        else:
            graph = f"[0:V:0]{self.video_filter(request)}[video]"
        inputs = []
        current = "video"
        image_index = 0
        width, height = request.dimensions()
        for index, (layer, asset) in enumerate(layers or []):
            label = f"layer{index}"
            if layer.kind == "text":
                graph += f";[{current}]ass={asset}[{label}]"
            else:
                image_index += 1
                inputs += ["-protocol_whitelist", "file,pipe", "-f", "image2", "-pattern_type", "none", "-i", str(asset)]
                w = max(2, round(width * layer.size / 200) * 2)
                h = max(2, round(height * .4) * 2)
                x = f"W*{layer.x / 100:.6f}-w/2"
                y = f"H*{layer.y / 100:.6f}-h/2"
                end = min(layer.end or (request.end - request.start), request.end - request.start)
                enable = f"gte(t,{layer.start:.6f})*lt(t,{end:.6f})"
                graph += (
                    f";[{image_index}:v:0]format=rgba,scale={w}:{h}:force_original_aspect_ratio=decrease:"
                    f"force_divisible_by=2,colorchannelmixer=aa={layer.opacity / 100:.3f},format=yuva420p[logo{index}];"
                    f"[{current}][logo{index}]overlay=x='{x}':y='{y}':eof_action=repeat:enable='{enable}'[{label}]"
                )
            current = label
        if use_ass:
            graph += f";[{current}]ass=overlay.ass[captioned]"
            current = "captioned"
        if use_ass or layers or request.fit in ("blur", "split"):
            video = ["-filter_complex_threads", "2", "-filter_complex", graph, "-map", f"[{current}]"]
        else:
            video = ["-map", "0:V:0", "-vf", self.video_filter(request)]
        if use_ass or layers:
            source, output = source.resolve(), output.resolve()
        return [self.require("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-protocol_whitelist", "file,pipe", "-ss", str(request.start), "-i", str(source), *inputs,
                "-t", str(request.end - request.start),
                *video, "-map", "0:a:0?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-map_metadata", "-1",
                "-progress", "pipe:1", "-nostats", str(output)]

    def proxy_command(self, source: Path, output: Path) -> list[str]:
        return [self.require("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe", "-i", str(source),
                "-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=trunc(iw*sar/2)*2:ih,setsar=1,scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart", "-map_metadata", "-1", "-progress", "pipe:1", "-nostats", str(output)]
