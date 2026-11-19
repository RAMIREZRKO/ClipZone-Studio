"""AutoClipping local sobre el búfer directo. La API de OBS sigue siendo manual."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from importlib.util import find_spec
import logging
import os
from pathlib import Path
from shutil import copyfile
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, RLock, Thread
from time import monotonic, time
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from ..ai.live_detector import AudioSignal, LiveDetector, editorial_score
from ..ai.models import capabilities
from ..database import now
from .analysis import AnalysisQueue
from .direct_buffer import AUTO_PLAYLIST, SESSION_NAME, Segment, write_playlist
from .direct_capture import MIN_FREE, CaptureSession, DirectCapture
from .direct_source import terminate_tree
from .media import CREATE_NO_WINDOW, MediaError
from .obs import LiveError

logger = logging.getLogger("clipzone.autoclip")
MAX_BYTES = 512 * 1024**2
CAPTURE_STATES = {"capturing", "reconnecting"}


class AutoOptions(BaseModel):
    enabled: bool = False
    model: Literal["tiny", "base", "small"] = "tiny"
    duration: Literal[30, 60, 90] = 30
    sensitivity: Literal["low", "balanced", "high"] = "balanced"
    minimum_score: int = Field(default=58, ge=0, le=100)
    before: int = Field(default=12, ge=0, le=80)
    after: int = Field(default=8, ge=0, le=30)
    per_hour: int = Field(default=6, ge=1, le=20)
    interval: int = Field(default=40, ge=5, le=600)

    @model_validator(mode="after")
    def timing(self):
        if self.before + self.after > self.duration:
            raise ValueError("La suma de los segundos anteriores y posteriores debe caber en la duración del clip.")
        return self

    def window(self, event: float) -> tuple[float, float]:
        return event + self.after - self.duration, event + self.after


def overlap(first: tuple[float, float], second: tuple[float, float]) -> bool:
    common = min(first[1], second[1]) - max(first[0], second[0])
    return common > .4 * min(first[1] - first[0], second[1] - second[0])


class AutoClip:
    def __init__(self, direct: DirectCapture, analysis: AnalysisQueue):
        self.direct, self.analysis = direct, analysis
        self.library, self.media = direct.library, direct.media
        self.settings, self.db = direct.settings, direct.library.db
        self.root = self.settings.data_dir.resolve() / "autoclips"
        self.lock, self.review_lock = RLock(), RLock()
        self.shutdown_event, self.wake, self.cancel = Event(), Event(), Event()
        self.options = AutoOptions()
        self.stage, self.message = "disabled", None
        self.detected = self.filtered = self.skipped = 0
        self.last_detection = float("-inf")
        self.pending = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipzone-auto-candidate")
        rows = self.db.list("autoclips")
        self.saved = deque(sorted(datetime.fromisoformat(row["created_at"]).timestamp() for row in rows
                                  if datetime.fromisoformat(row["created_at"]).timestamp() >= time() - 3600))
        self.windows: deque[tuple[str, tuple[float, float]]] = deque(maxlen=80)
        self.clean_files(rows)
        self.monitor = Thread(target=self.run, name="clipzone-auto-listen", daemon=True)
        self.monitor.start()

    def clean_files(self, rows: list[dict]) -> None:
        keep = {row["id"] for row in rows if row["status"] == "pending"}
        for path in self.root.iterdir():
            if SESSION_NAME.fullmatch(path.stem) and path.suffix in {".mp4", ".jpg", ".part"}:
                if path.stem not in keep or path.suffix == ".part":
                    self.remove_file(path)

    @staticmethod
    def remove_file(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("No se pudo retirar un archivo temporal de AutoClipping: %s", path.name)

    def size(self) -> int:
        sizes = []
        for path in self.root.iterdir():
            if path.suffix in {".mp4", ".jpg", ".part"} and SESSION_NAME.fullmatch(path.stem) and not path.is_symlink():
                try:
                    sizes.append(path.stat().st_size)
                except FileNotFoundError:
                    continue
        return sum(sizes)

    def status(self) -> dict:
        caps = capabilities(self.settings)
        with self.lock:
            return {"options": self.options.model_dump(), "stage": self.stage, "message": self.message,
                    "detected": self.detected, "filtered": self.filtered, "skipped": self.skipped,
                    "bytes": self.size(), "max_bytes": MAX_BYTES, "vad": find_spec("webrtcvad") is not None,
                    "whisper": all(caps["dependencies"].values()), "models": caps["models"]}

    def configure(self, options: AutoOptions) -> dict:
        if options.enabled:
            self.direct.engine.require()
            self.media.require("ffmpeg")
            caps = capabilities(self.settings)
            if not find_spec("webrtcvad"):
                raise LiveError("auto_dependency", "Instala backend/requirements-autoclip.txt para detectar actividad de voz.", 409)
            if not all(caps["dependencies"].values()) or not any(
                model["id"] == options.model and model["installed"] for model in caps["models"]
            ):
                raise LiveError("auto_model", "Instala primero el modelo de Whisper elegido desde Momentos con IA.", 409)
        with self.lock:
            if self.options != options:
                self.cancel.set()
                self.cancel = Event()
                self.options = options
                self.stage = "waiting" if options.enabled else "disabled"
                self.message = None
                self.wake.set()
        return self.status()

    def activity(self, token: Event, stage: str, message: str | None = None) -> None:
        with self.lock:
            if not token.is_set():
                self.stage, self.message = stage, message

    def next_audio(self, previous: str | None) -> tuple[CaptureSession, int, Segment] | None:
        with self.direct.lock:
            session = self.direct.session
            if not session or session.state not in CAPTURE_STATES or not session.buffer.closed:
                return None
            buffer = session.buffer
            closed = list(buffer.closed)
            newest = closed[-1]
            if str(newest.path) == previous:
                return None
            upcoming = next((item for old, item in zip(closed, closed[1:]) if str(old.path) == previous), newest)
            if newest.start - upcoming.start > 5:
                upcoming = newest
            return session, buffer.epoch, buffer.hold([upcoming])[0]

    def run(self) -> None:
        previous = identity = token = detector = None
        end = 0.
        idle = False
        while not self.shutdown_event.is_set():
            with self.lock:
                options, current = self.options, self.cancel
            if not options.enabled:
                self.wake.wait()
                self.wake.clear()
                continue
            if current is not token:
                token, identity, previous = current, None, None
            picked = self.next_audio(previous)
            if picked is None:
                with self.direct.lock:
                    session = self.direct.session
                    inactive = not session or session.state not in CAPTURE_STATES or not session.buffer.closed
                if inactive and not idle:
                    with self.lock:
                        if not self.pending and self.stage not in {"error", "waiting"}:
                            self.activity(token, "waiting")
                    idle = True
                self.shutdown_event.wait(.25)
                continue
            idle = False
            session, epoch, segment = picked
            previous = str(segment.path)
            identity_now = (session.buffer.folder, epoch)
            try:
                if identity != identity_now or abs(end - segment.start) > .8:
                    detector = LiveDetector(options.sensitivity)
                    identity = identity_now
                end = segment.start + segment.duration
                data = self.pcm(["-i", str(segment.path)], duration=min(9, segment.duration))
                with self.lock:
                    if not self.pending:
                        message = self.message if data and self.stage != "waiting" else None
                        self.activity(token, "listening", message if data else "Esperando segmentos con audio.")
                if data:
                    for signal in detector.feed(data, segment.start):
                        self.propose(session, epoch, signal, options, token)
            except (OSError, ValueError, MediaError, ImportError, subprocess.SubprocessError):
                self.activity(token, "error", "No se pudo leer el audio del búfer.")
                logger.exception("Falló la lectura de audio de AutoClipping.")
            finally:
                self.direct.release_segments(session, (segment,))

    def pcm(self, inputs: list[str], duration: float, start=0., cwd=None) -> bytes:
        result = subprocess.run([self.media.require("ffmpeg"), "-hide_banner", "-v", "error", "-nostdin",
                                 "-protocol_whitelist", "file,pipe", *inputs, "-ss", f"{start:.6f}",
                                 "-t", f"{duration:.6f}", "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
                                 "-threads", "1", "-f", "s16le", "pipe:1"], cwd=cwd, capture_output=True,
                                creationflags=CREATE_NO_WINDOW, timeout=12)
        return result.stdout if result.returncode == 0 else b""

    def propose(self, session: CaptureSession, epoch: int, signal: AudioSignal, options: AutoOptions, token: Event) -> None:
        origin = f"{session.buffer.folder.name}:{epoch}"
        span = options.window(signal.time)
        with self.lock:
            if token.is_set() or self.shutdown_event.is_set():
                return
            self.detected += 1
            clock = monotonic()
            while self.saved and self.saved[0] <= time() - 3600:
                self.saved.popleft()
            if (self.pending or clock - self.last_detection < options.interval or len(self.saved) >= options.per_hour or
                    any(key == origin and overlap(previous, span) for key, previous in self.windows)):
                self.skipped += 1
                return
            self.last_detection = clock
            self.activity(token, "collecting")
            self.pending = self.executor.submit(self.process, session, epoch, origin, signal, options, token, span)

    def collect(self, session: CaptureSession, epoch: int, window: tuple[float, float], event: float,
                options: AutoOptions, token: Event, held: dict[Path, Segment]) -> tuple[float, float] | None:
        deadline = monotonic() + options.after + 18
        while not token.is_set() and monotonic() < deadline:
            with self.direct.lock:
                buffer = session.buffer
                if self.direct.session is not session or buffer.epoch != epoch or not buffer.closed:
                    return None
                start = max(window[0], next(iter(held.values())).start if held else buffer.closed[0].start)
                if start > event - options.before + .03:
                    return None
                choices = [item for item in buffer.closed if item.start < window[1] and item.start + item.duration > start]
                new = [item for item in choices if item.path not in held]
                # Deja margen al búfer circular y a un guardado manual paralelo.
                if sum(item.path.stat().st_size for item in (*held.values(), *new)) > self.direct.max_bytes * .45:
                    raise LiveError("auto_disk", "El candidato excede el margen reservado del búfer temporal.")
                for item in buffer.hold(new):
                    held[item.path] = item
                if choices and choices[-1].start + choices[-1].duration >= window[1] - .025:
                    # Usa las duraciones ya estabilizadas en los bordes que siguen en el búfer.
                    for item in choices:
                        held[item.path].duration = item.duration
                    return start, min(window[1], choices[-1].start + choices[-1].duration)
                if session.state not in CAPTURE_STATES:
                    return None
            token.wait(.25)
        return None

    def process(self, session, epoch, origin, signal, options, token, window) -> None:
        held: dict[Path, Segment] = {}
        folder = session.buffer.folder
        playlist = folder / AUTO_PLAYLIST
        candidate_id = uuid4().hex
        committed = False
        try:
            span = self.collect(session, epoch, window, signal.time, options, token, held)
            if not span or token.is_set():
                self.skip(token, "El búfer anterior o posterior no llegó a completarse.")
                return
            segments = tuple(held.values())
            if any(item.path.resolve() != item.path for item in segments):
                raise LiveError("auto_storage", "No se encontró un segmento temporal válido.")
            write_playlist(playlist, segments)
            inputs = ["-f", "concat", "-safe", "1", "-i", playlist.name]
            audio_start = max(span[0], signal.time - 14)
            audio_end = min(span[1], audio_start + 24)
            self.activity(token, "transcribing")
            sound = self.pcm(inputs, audio_end - audio_start, audio_start - segments[0].start, folder)
            if not sound:
                self.skip(token, "El candidato no contiene audio utilizable.")
                return
            with TemporaryDirectory(prefix="clipzone-auto-") as temp:
                audio, result = Path(temp) / "event.pcm", Path(temp) / "event.json"
                audio.write_bytes(sound)
                transcript = self.analysis.transcribe_live(audio, options.model, result, token)
            if transcript is None:
                self.skip(token, "Whisper está ocupado o se canceló el análisis.")
                return
            editorial = editorial_score(transcript, signal.time - audio_start, signal)
            if not editorial or editorial["score"] < options.minimum_score:
                with self.lock:
                    if not token.is_set():
                        self.filtered += 1
                self.activity(token, "listening", "Candidato bajo el umbral o sin contexto transcrito suficiente.")
                return
            if token.is_set():
                return
            self.activity(token, "saving")
            movie = self.root / f"{candidate_id}.mp4"
            info = self.render(inputs, folder, movie, span[0] - segments[0].start, span[1] - span[0], token)
            with self.lock:
                if not info or token.is_set():
                    return
                row = {**editorial, "id": candidate_id, "status": "pending", "created_at": now(),
                       "duration": info["duration"], "size": movie.stat().st_size, "model": options.model,
                       "platform": session.source.platform, "channel": session.source.channel, "quality": session.quality,
                       "requested_seconds": options.duration, "video_id": None}
                self.db.put("autoclips", row)
                committed = True
                self.saved.append(time())
                self.windows.append((origin, span))
            self.activity(token, "listening", "Candidato guardado para revisión.")
        except (LiveError, MediaError, OSError, RuntimeError, ValueError, subprocess.SubprocessError, sqlite3.Error) as exc:
            logger.warning("Falló un candidato de AutoClipping", exc_info=True)
            message = str(exc) if isinstance(exc, (LiveError, MediaError, RuntimeError)) else "No se pudo completar el candidato."
            self.activity(token, "error", message)
        finally:
            self.remove_file(playlist)
            if not committed:
                self.remove_temporary(candidate_id)
            self.direct.release_segments(session, tuple(held.values()))
            with self.lock:
                self.pending = None

    def skip(self, token: Event, message: str) -> None:
        with self.lock:
            if not token.is_set():
                self.skipped += 1
                self.activity(token, "skipped", message)

    def render(self, inputs, folder, movie, start, duration, token: Event) -> dict | None:
        budget = min(MAX_BYTES - self.size(), (self.direct.disk_free() or 0) - MIN_FREE) - 1024**2
        if budget < 8 * 1024**2:
            raise LiveError("auto_disk", "Falta espacio para más candidatos. Conserva o descarta los pendientes.")
        temporary = movie.with_suffix(".part")
        command = [self.media.require("ffmpeg"), "-hide_banner", "-v", "error", "-nostdin", "-y",
                   "-protocol_whitelist", "file,pipe", "-threads", "2", *inputs, "-ss", f"{start:.6f}",
                   "-t", f"{duration:.6f}", "-map", "0:V:0", "-map", "0:a:0", "-filter_threads", "1",
                   "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-threads:v", "2", "-preset", "veryfast",
                   "-crf", "21", "-maxrate", "8M", "-bufsize", "8M", "-pix_fmt", "yuv420p", "-c:a", "aac",
                   "-fs", str(budget), "-movflags", "+faststart", "-f", "mp4", str(temporary)]
        deadline = monotonic() + 105
        with subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
                              start_new_session=os.name != "nt") as process:
            try:
                while process.poll() is None:
                    if token.wait(.25):
                        return None
                    if monotonic() > deadline:
                        raise MediaError("El render de AutoClipping tardó demasiado.")
                if process.returncode:
                    raise MediaError("No se pudo renderizar el candidato.")
            finally:
                terminate_tree(process)
        info = self.media.probe(temporary)
        if not info["has_audio"] or abs(info["duration"] - duration) > .35 or temporary.stat().st_size > budget:
            raise LiveError("auto_incomplete", "El candidato quedó incompleto. Revisa el espacio libre y el estado del directo.")
        temporary.replace(movie)
        self.media.thumbnail(movie, movie.with_suffix(".jpg"))
        return info

    def row(self, identifier: str) -> dict:
        row = self.db.get("autoclips", identifier) if SESSION_NAME.fullmatch(identifier) else None
        if not row:
            raise LiveError("auto_missing", "No se encontró el candidato.", 404)
        return row

    def media_path(self, candidate: dict, suffix: str) -> Path:
        path = self.root / (candidate["id"] + suffix)
        if candidate["status"] != "pending" or path.resolve() != path or not path.is_file():
            raise LiveError("auto_missing", "El archivo temporal del candidato ya no está disponible.", 404)
        return path

    def remove_temporary(self, identifier: str) -> None:
        for suffix in (".mp4", ".jpg", ".part"):
            self.remove_file(self.root / (identifier + suffix))

    def review(self, identifier: str, keep: bool) -> dict:
        with self.review_lock:
            row = self.row(identifier)
            if row["status"] == ("kept" if keep else "discarded"):
                return row
            if row["status"] != "pending":
                raise LiveError("auto_reviewed", "El candidato ya tiene una decisión registrada.")
            if keep:
                movie = self.media_path(row, ".mp4")
                if (self.direct.disk_free() or 0) < movie.stat().st_size + MIN_FREE:
                    raise LiveError("auto_disk", "No hay espacio para incorporar el candidato a Mis vídeos.", 507)
                with self.library.stage(".mp4") as staged:
                    copyfile(movie, staged.partial)
                    row = {**row, "status": "kept", "video_id": staged.id}
                    live = {key: row[key] for key in ("platform", "quality", "requested_seconds")}
                    self.library.finish(staged, row["title"] + ".mp4",
                                        {**live, "method": "auto", "captured_at": row["created_at"]}, row)
            else:
                row = self.db.put("autoclips", {**row, "status": "discarded"})
            self.remove_temporary(identifier)
            return row

    def shutdown(self) -> None:
        with self.lock:
            self.cancel.set()
            self.shutdown_event.set()
            self.wake.set()
        self.monitor.join()
        self.executor.shutdown(wait=True, cancel_futures=True)


def register_autoclip(app: FastAPI, public_video):
    def public(row: dict) -> dict:
        video = app.state.db.get("videos", row["video_id"]) if row["video_id"] else None
        base = f"/api/live/auto/candidates/{row['id']}"
        return {**row, "video": public_video(video) if video else None,
                "preview_url": f"{base}/preview" if row["status"] == "pending" else None,
                "thumbnail_url": f"{base}/thumbnail" if row["status"] == "pending" else None}

    @app.get("/api/live/auto/status")
    def status():
        return app.state.autoclip.status()

    @app.post("/api/live/auto/config")
    def configure(body: AutoOptions):
        return app.state.autoclip.configure(body)

    @app.get("/api/live/auto/candidates")
    def history():
        return [public(row) for row in app.state.db.list("autoclips", limit=100)]

    @app.get("/api/live/auto/candidates/{identifier}/{kind}")
    def media(identifier: str, kind: Literal["preview", "thumbnail"]):
        service = app.state.autoclip
        suffix, mime = (".mp4", "video/mp4") if kind == "preview" else (".jpg", "image/jpeg")
        return FileResponse(service.media_path(service.row(identifier), suffix), media_type=mime)

    @app.post("/api/live/auto/candidates/{identifier}/{decision}")
    def review(identifier: str, decision: Literal["keep", "discard"]):
        try:
            return public(app.state.autoclip.review(identifier, decision == "keep"))
        except MediaError as exc:
            raise LiveError("auto_media", str(exc), 422) from exc
        except OSError as exc:
            raise LiveError("auto_storage", "No se pudo incorporar el candidato. Revisa el disco o los permisos.", 507) from exc
