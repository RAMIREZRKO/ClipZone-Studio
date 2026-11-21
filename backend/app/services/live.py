"""Captura puntual del búfer de OBS e importación a la biblioteca local."""
import errno
import logging
from pathlib import Path
from shutil import copyfile, disk_usage
import subprocess
from threading import Lock
from typing import Callable, Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import Settings
from ..database import now
from ..storage_location import CAPTURE_STOP, LocationError
from .direct_capture import DirectSaveRequest, SourceRequest, StartRequest
from .library import SUPPORTED_VIDEO, VideoLibrary
from .media import CREATE_NO_WINDOW, MediaError
from .multistream import CaptureLimit, StreamerSettings
from .obs import LiveError, ObsSession, obs_session

logger = logging.getLogger("clipzone.live")
MIN_FREE = CAPTURE_STOP
MAX_REPLAY_SECONDS = 90


class CaptureRequest(BaseModel):
    seconds: Literal[30, 60, 90]


def check_obs_idle(settings: Settings) -> None:
    connected = False
    try:
        with obs_session(int(settings.obs_port), settings.obs_password) as session:
            connected = True
            if session.request("GetReplayBufferStatus").get("outputActive") is True:
                raise LocationError("Detén el búfer de repetición de OBS antes de migrar el almacenamiento.")
    except LiveError as exc:
        if connected or exc.code not in {"obs_offline", "obs_timeout"}:
            raise LocationError("No se pudo confirmar que OBS esté inactivo. Detén el búfer y revisa la conexión de OBS.") from exc


class LiveCapture:
    def __init__(self, settings: Settings, library: VideoLibrary):
        self.settings = settings
        self.library = library
        self.media = library.media
        self.lock = Lock()

    def replay_dir(self) -> Path:
        path = Path(self.settings.obs_replay_dir or self.settings.data_dir.resolve() / "live-inbox")
        if not path.is_absolute() or path.drive.startswith("\\\\"):
            raise LiveError("obs_folder", "La carpeta de OBS debe ser una ruta absoluta en un disco local.")
        try:
            allowed = path.resolve(strict=True)
            if allowed.drive.startswith("\\\\") or not allowed.is_dir():
                raise OSError
            return allowed
        except (OSError, RuntimeError) as exc:
            raise LiveError("obs_folder", "La carpeta de repeticiones no está disponible. Revisa CLIPZONE_OBS_REPLAY_DIR.") from exc

    def port(self) -> int:
        try:
            port = int(self.settings.obs_port)
            if not 1 <= port <= 65535:
                raise ValueError
            return port
        except ValueError as exc:
            raise LiveError("obs_port", "CLIPZONE_OBS_PORT debe ser un puerto entre 1 y 65535.") from exc

    @staticmethod
    def profile(session: ObsSession, folder: Path) -> int:
        mode = session.profile("Output", "Mode")
        if mode not in {"Simple", "Advanced"}:
            raise LiveError("obs_profile", "No se reconoce el modo de salida del perfil de OBS.")
        category, path_key = ("AdvOut", "RecFilePath") if mode == "Advanced" else ("SimpleOutput", "FilePath")
        directory = session.profile(category, path_key)
        try:
            obs_path = Path(directory or "")
            if not obs_path.is_absolute() or obs_path.resolve(strict=True) != folder:
                raise ValueError
        except (ValueError, OSError, RuntimeError) as exc:
            raise LiveError("obs_folder", "La ruta de grabación de OBS debe coincidir con la carpeta indicada en ClipZone Live.") from exc
        try:
            seconds = int(session.profile(category, "RecRBTime") or "")
            if not 1 <= seconds <= MAX_REPLAY_SECONDS:
                raise ValueError
        except ValueError as exc:
            raise LiveError("obs_buffer_limit", "Ajusta el tiempo máximo del búfer de OBS entre 1 y 90 s y vuelve a iniciarlo.") from exc
        return seconds

    @staticmethod
    def free(folder: Path) -> int:
        try:
            return disk_usage(folder).free
        except OSError as exc:
            raise LiveError("disk_unavailable", "No se pudo consultar el espacio libre del disco.") from exc

    def status(self) -> dict:
        result = {"connected": False, "buffer_active": False, "buffer_seconds": None, "ready": False,
                  "busy": self.lock.locked(), "port": self.settings.obs_port, "error": None, "error_code": None,
                  "replay_dir": self.settings.obs_replay_dir or str(self.settings.data_dir.resolve() / "live-inbox"),
                  "replay_free_bytes": None, "library_free_bytes": None}
        storage_error = None
        folder = None
        try:
            result["library_free_bytes"] = self.free(self.settings.data_dir)
            folder = self.replay_dir()
            result["replay_dir"] = str(folder)
            result["replay_free_bytes"] = self.free(folder)
            if min(result["library_free_bytes"], result["replay_free_bytes"]) <= MIN_FREE:
                raise LiveError("disk_full", "Se necesitan más de 5 GB libres en los discos de OBS y de ClipZone.")
        except LiveError as exc:
            storage_error = exc
        try:
            with obs_session(self.port(), self.settings.obs_password) as session:
                result["connected"] = True
                result["buffer_active"] = session.request("GetReplayBufferStatus").get("outputActive") is True
                if storage_error:
                    raise storage_error
                result["buffer_seconds"] = self.profile(session, folder)
                if not self.settings.binary("ffmpeg") or not self.settings.binary("ffprobe"):
                    raise LiveError("media_missing", "FFmpeg y FFprobe son necesarios para importar la captura.")
                result["ready"] = result["buffer_active"]
        except LiveError as exc:
            result.update(error=str(exc), error_code=exc.code)
        return result

    def stop_for_low_storage(self) -> None:
        if not self.lock.acquire(blocking=False):
            return
        try:
            folder = self.replay_dir()
            if min(self.free(folder), self.free(self.settings.data_dir)) > MIN_FREE:
                return
            with obs_session(self.port(), self.settings.obs_password) as session:
                if session.request("GetReplayBufferStatus").get("outputActive") is True:
                    self.profile(session, folder)
                    session.request("StopReplayBuffer")
                    logger.warning("OBS: búfer de repetición detenido al llegar al límite de espacio.")
        except LiveError:
            # Si OBS está desconectado o usa otra carpeta, no hay un búfer autorizado que detener.
            return
        finally:
            self.lock.release()

    @staticmethod
    def replay_file(value: str, folder: Path) -> Path:
        try:
            announced = Path(value)
            if not announced.is_absolute():
                raise LiveError("obs_file", "OBS devolvió una ruta de repetición que no es absoluta.")
            replay = announced.resolve(strict=True)
            if not replay.is_relative_to(folder) or replay == folder:
                raise LiveError("obs_file_outside", "OBS guardó la repetición fuera de la carpeta autorizada de ClipZone Live.")
            if not replay.is_file() or replay.suffix.lower() not in SUPPORTED_VIDEO:
                raise LiveError("obs_format", "La repetición debe ser un vídeo admitido, como MP4 o MKV.")
            return replay
        except (OSError, ValueError, RuntimeError) as exc:
            raise LiveError("obs_file", "No se pudo abrir el archivo que OBS anunció. Comprueba la carpeta y los permisos.") from exc

    def capture(self, seconds: int) -> tuple[dict, dict]:
        if not self.lock.acquire(blocking=False):
            raise LiveError("capture_busy", "Ya se está guardando una captura de ClipZone Live.")
        try:
            return self.capture_once(seconds)
        except OSError as exc:
            if exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) in {39, 112}:
                raise LiveError("disk_full", "Se agotó el espacio durante la importación. El archivo de OBS se conserva.", 507) from exc
            raise LiveError("import_io", "No se pudo leer o copiar la repetición. Comprueba si el archivo está bloqueado o si faltan permisos.") from exc
        finally:
            self.lock.release()

    def capture_once(self, seconds: int) -> tuple[dict, dict]:
        self.media.require("ffmpeg")
        self.media.require("ffprobe")
        folder = self.replay_dir()
        if min(self.free(folder), self.free(self.settings.data_dir)) <= MIN_FREE:
            raise LiveError("disk_full", "Se necesitan al menos 128 MiB libres en los discos de OBS y de ClipZone.", 507)
        with obs_session(self.port(), self.settings.obs_password, outputs=True) as session:
            if session.request("GetReplayBufferStatus").get("outputActive") is not True:
                raise LiveError("buffer_inactive", "Inicia el búfer de repetición desde OBS antes de guardar.")
            self.profile(session, folder)
            captured_at = now()
            saved_path = session.save()
        replay = self.replay_file(saved_path, folder)
        size = replay.stat().st_size
        if size > self.settings.max_upload_bytes:
            raise LiveError("capture_too_large", "El archivo que guardó OBS supera el límite local de importación.", 413)
        if self.free(self.settings.data_dir) < size + MIN_FREE:
            raise LiveError("disk_full", "Falta espacio para importar la repetición. El archivo de OBS se conserva.", 507)
        duration = self.media.probe(replay)["duration"]
        # OBS puede añadir un GOP al intervalo máximo. Rechaza archivos desproporcionados.
        if duration > MAX_REPLAY_SECONDS + 30:
            raise LiveError("obs_replay_duration", "El archivo que guardó OBS excede la duración esperada. Revisa el perfil y reinicia el búfer.")
        trim = duration > seconds
        suffix = ".mp4" if trim else replay.suffix.lower()
        live = {"method": "obs", "requested_seconds": seconds, "captured_at": captured_at}
        with self.library.stage(suffix) as staged:
            if trim:
                self.trim_tail(replay, staged.partial, duration - seconds, seconds)
            else:
                copyfile(replay, staged.partial)
            if staged.partial.stat().st_size > self.settings.max_upload_bytes:
                raise LiveError("capture_too_large", "La captura supera el límite local de importación.", 413)
            video = self.library.finish(staged, replay.stem + suffix, live)
        return {**live, "id": video["id"], "name": video["name"], "duration": video["duration"], "size": video["size"]}, video

    def trim_tail(self, replay: Path, target: Path, start: float, seconds: int):
        command = [self.media.require("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-protocol_whitelist", "file,pipe", "-threads", "2", "-ss", f"{start:.6f}", "-i", str(replay),
                   "-t", str(seconds), "-map", "0:V:0", "-map", "0:a?", "-filter_threads", "1",
                   "-c:v", "libx264", "-threads:v", "2", "-preset", "veryfast", "-crf", "20",
                   "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-movflags", "+faststart", "-f", "mp4", str(target)]
        try:
            result = subprocess.run(command, capture_output=True, timeout=240, creationflags=CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as exc:
            raise LiveError("trim_timeout", "El recorte tardó demasiado. Puedes importar manualmente el archivo que guardó OBS.", 504) from exc
        if result.returncode:
            stderr = result.stderr.decode("utf-8", errors="replace")
            logger.warning("FFmpeg no pudo recortar la repetición (código %s): %s", result.returncode, stderr[-1200:])
            if self.free(self.settings.data_dir) < MIN_FREE:
                raise LiveError("disk_full", "Se agotó el espacio durante el recorte. El archivo de OBS se conserva.", 507)
            raise LiveError("trim_failed", "FFmpeg no pudo recortar la repetición. El archivo de OBS se conserva.", 422)


def register_live(app: FastAPI, public_video: Callable[[dict], dict]):
    def serialize(capture: dict, video: dict | None) -> dict:
        return {**capture, "video": public_video(video) if video else None}

    @app.exception_handler(LiveError)
    async def live_error(_request: Request, exc: LiveError):
        logger.warning("ClipZone Live: %s (HTTP %s)", exc.code, exc.status)
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status)

    @app.get("/api/live/status")
    def live_status():
        return app.state.live.status()

    @app.get("/api/live/captures")
    def live_history():
        return [serialize(capture, video) for capture, video in app.state.db.live_captures()]

    @app.post("/api/live/captures", status_code=201)
    def save_replay(body: CaptureRequest):
        try:
            capture, video = app.state.live.capture(body.seconds)
        except MediaError as exc:
            raise LiveError("capture_media", str(exc), 422) from exc
        return serialize(capture, video)

    @app.get("/api/live/direct/status")
    def direct_status(slot: int = Query(0, ge=0, le=1), streamer: str | None = None):
        return app.state.multistream.capture_status(streamer, slot)

    @app.get("/api/live/direct/channels")
    def direct_channels():
        return app.state.multistream.overview()

    @app.put("/api/live/direct/settings")
    def direct_settings(body: CaptureLimit):
        return app.state.multistream.configure_limit(body)

    @app.post("/api/live/direct/probe")
    def direct_probe(body: SourceRequest, streamer: str | None = None):
        return app.state.multistream.inspect(body, streamer)

    @app.get("/api/live/streamers")
    def streamer_templates():
        return app.state.db.list("streamers")

    @app.post("/api/live/streamers")
    def streamer_template(body: StreamerSettings, streamer: str | None = None):
        return app.state.multistream.update(body, streamer)

    @app.delete("/api/live/streamers/{identifier}")
    def remove_streamer(identifier: str):
        app.state.multistream.remove(identifier)
        return {"id": identifier}

    @app.post("/api/live/direct/start", status_code=202)
    def direct_start(body: StartRequest, slot: int = Query(0, ge=0, le=1), streamer: str | None = None):
        return app.state.multistream.start(body, streamer, slot)

    @app.post("/api/live/direct/stop")
    def direct_stop(slot: int = Query(0, ge=0, le=1), streamer: str | None = None):
        return app.state.multistream.stop(streamer, slot)

    @app.post("/api/live/direct/captures", status_code=201)
    def direct_save(body: DirectSaveRequest, slot: int = Query(0, ge=0, le=1), streamer: str | None = None):
        try:
            capture, video = app.state.multistream.save(body.seconds, streamer, slot)
        except MediaError as exc:
            raise LiveError("capture_media", str(exc), 422) from exc
        return serialize(capture, video)
