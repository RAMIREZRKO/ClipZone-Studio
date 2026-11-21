"""Resuelve canales públicos con los complementos integrados de Streamlink."""
from dataclasses import dataclass, field
from importlib.util import find_spec
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from threading import Event
from time import monotonic
from urllib.parse import urlsplit

from .media import CREATE_NO_WINDOW
from .obs import LiveError
from .youtube_live import YOUTUBE_HOSTS, youtube_url

QUALITY = re.compile(r"[0-9]{2,4}p[0-9]{0,3}(?:_alt[0-9]*)?|source|live")
CHANNEL = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_-]{0,49}")


@dataclass(frozen=True)
class DirectSource:
    platform: str
    channel: str
    url: str
    name: str | None = None
    manifest: str | None = field(default=None, repr=False)
    verified_live: bool = False


def source_from_url(url: str) -> DirectSource:
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname or ""
        if (parts.scheme != "https" or parts.username is not None or parts.password is not None
                or parts.port is not None or parts.fragment or not parts.netloc
                or parts.netloc.lower() != host):
            raise ValueError
        if host in YOUTUBE_HOSTS:
            canonical, channel = youtube_url(parts)
            return DirectSource("youtube", channel, canonical)
        if parts.query:
            raise ValueError
    except ValueError as exc:
        raise LiveError("direct_url", "Usa la URL HTTPS de un canal, sin parámetros ni credenciales.", 422) from exc
    platforms = {"kick.com": "kick", "www.kick.com": "kick", "twitch.tv": "twitch", "www.twitch.tv": "twitch"}
    channel = parts.path.removeprefix("/").removesuffix("/")
    if host not in platforms or not CHANNEL.fullmatch(channel) or channel.lower() in {"videos", "clips", "directory", "search", "embed", "login"}:
        raise LiveError("direct_url", "Usa la URL HTTPS de un canal de Kick, Twitch o YouTube Live.", 422)
    platform = platforms[host]
    channel = channel.lower()
    canonical = "kick.com" if platform == "kick" else "www.twitch.tv"
    return DirectSource(platform, channel, f"https://{canonical}/{channel}")


def quality_weight(name: str) -> tuple[int, int, str]:
    resolution = re.match(r"(\d+)p(\d+)?", name)
    if resolution:
        return int(resolution[1]), int(resolution[2] or 0), name
    return (10_000 if name == "source" else 0), 0, name


def terminate_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=CREATE_NO_WINDOW, timeout=3)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=3)


class StreamlinkSource:
    def __init__(self, ffmpeg: str | None = None):
        self.ffmpeg = ffmpeg

    def available(self) -> bool:
        return find_spec("streamlink") is not None

    def require(self) -> None:
        if not self.available():
            raise LiveError("streamlink_missing", "Instala Streamlink con .\\.venv\\Scripts\\python.exe -m pip install -r backend/requirements-live.txt.", 503)

    def command(self, source: DirectSource | None = None) -> list[str]:
        self.require()
        youtube = source is not None and source.platform == "youtube"
        mux = ["--ffmpeg-ffmpeg", self.ffmpeg, "--ffmpeg-fout", "mpegts"] if youtube and self.ffmpeg else []
        return [sys.executable, "-I", "-m", "streamlink", "--no-config", "--no-plugin-cache", "--no-plugin-sideloading",
                "--webbrowser", "no", "--http-ignore-env", "--http-timeout", "6", "--stream-timeout", "12",
                "--stream-types", "hls,hls-multi" if youtube else "hls", *mux,
                "--stream-segment-attempts", "2", "--stream-segment-timeout", "6",
                "--stream-segment-threads", "2", "--ringbuffer-size", "16M", "--retry-open", "1"]

    @staticmethod
    def input_url(source: DirectSource) -> str:
        if source.platform != "youtube":
            return source.url
        if not source.verified_live:
            raise LiveError("direct_access", "Confirma que el directo de YouTube esté activo y sea público.", 403)
        return "hls://" + source.manifest if source.manifest else source.url

    @staticmethod
    def spawn(command: list[str], *, stderr=subprocess.DEVNULL) -> subprocess.Popen:
        env = {k: v for k, v in os.environ.items() if k.upper() != "CLIPZONE_OBS_PASSWORD"}
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=stderr,
                                creationflags=CREATE_NO_WINDOW, start_new_session=os.name != "nt", env=env)

    def inspect(self, source: DirectSource, cancelled: Event | None = None) -> list[str]:
        command = [*self.command(source), "--json", "--", self.input_url(source)]
        deadline = monotonic() + 14
        try:
            with self.spawn(command, stderr=subprocess.PIPE) as process:
                while True:
                    if cancelled is not None and cancelled.is_set():
                        terminate_tree(process)
                        return []
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        terminate_tree(process)
                        raise LiveError("direct_timeout", "La plataforma tardó demasiado en responder.", 504)
                    try:
                        stdout, stderr = process.communicate(timeout=min(remaining, .25) if cancelled is not None else remaining)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                returncode = process.returncode
        except OSError as exc:
            raise LiveError("streamlink_start", "No se pudo iniciar Streamlink.", 503) from exc
        try:
            info = json.loads(stdout) if stdout else {}
        except (ValueError, UnicodeError):
            info = {}
        return self.qualities(info, stderr, returncode)

    @staticmethod
    def qualities(info: dict, stderr: bytes, returncode: int) -> list[str]:
        if not isinstance(info, dict):
            info = {}
        detail = (str(info.get("error", "")) + " " + stderr.decode("utf-8", errors="replace")).lower()
        if re.search(r"\b(?:401|403|451)\b|age.restrict|login required|authentication required|subscriber.only|drm", detail):
            raise LiveError("direct_access", "La plataforma restringió el acceso. Usa un directo público y autorizado que no esté protegido.", 403)
        streams = info.get("streams", {})
        if isinstance(streams, dict) and streams:
            options = sorted((key for key in streams if QUALITY.fullmatch(key)), key=quality_weight, reverse=True)
            if options:
                return options
            raise LiveError("direct_quality", "El canal no ofrece una calidad HLS de vídeo compatible.", 422)
        if "no playable streams found" in detail or "is offline" in detail or (returncode == 0 and streams == {}):
            return []
        raise LiveError("direct_network", "No se pudo consultar el directo. Revisa la conexión o vuelve a comprobar el canal.", 502)

    def open(self, source: DirectSource, quality: str) -> subprocess.Popen:
        if not QUALITY.fullmatch(quality):
            raise LiveError("direct_quality", "Selecciona una calidad de vídeo disponible.", 422)
        return self.spawn([*self.command(source), "--loglevel", "error", "--stdout", "--", self.input_url(source), quality])

