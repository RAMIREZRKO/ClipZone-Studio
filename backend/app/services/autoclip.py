"""AutoClipping local sobre el búfer directo. La API de OBS sigue siendo manual."""
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from importlib.util import find_spec
import logging
import os
from pathlib import Path
from shutil import copyfile
import subprocess
from tempfile import TemporaryDirectory, TemporaryFile
from threading import Event, RLock, Thread
from time import monotonic, time
from typing import Literal, get_args
from uuid import uuid4

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from ..ai.live_detector import AudioSignal, DetectionMode, LiveDetector, editorial_score, has_speech_context
from ..ai.models import capabilities
from ..database import now
from ..storage_location import GB
from .analysis import AnalysisQueue, LiveWhisperError, LiveWhisperQueueTimeout
from .direct_buffer import AUTO_PLAYLIST, SESSION_NAME, Segment, write_playlist
from .direct_capture import MIN_FREE, CaptureSession, DirectCapture
from .direct_source import terminate_tree
from .media import CREATE_NO_WINDOW, MediaError
from .obs import LiveError

logger = logging.getLogger("clipzone.autoclip")
MIN_CANDIDATE_BYTES = 8 * 1024**2
RETRY_DELAY = 8
DEFERRED_LIMIT = 4
DEFERRED_AGE = 65
CAPTURE_STATES = {"capturing", "reconnecting"}


class CandidateStorage(BaseModel):
    limit_gb: Literal[1, 5, 10, 20]


class AutoFields(BaseModel):
    enabled: bool = False
    model: Literal["tiny", "base", "small"] = "tiny"
    detection_mode: DetectionMode = "mixed"
    duration: Literal[30, 60, 90] = 30
    sensitivity: Literal["low", "balanced", "high"] = "balanced"
    minimum_score: int = Field(default=58, ge=0, le=100)
    before: int = Field(default=12, ge=0, le=80)
    after: int = Field(default=8, ge=0, le=30)
    per_hour: int = Field(default=6, ge=1, le=20)
    interval: int = Field(default=40, ge=5, le=600)

    @field_validator("detection_mode", mode="before")
    @classmethod
    def legacy_mode(cls, value):
        return "irl" if value == "reaction" else value


class AutoOptions(AutoFields):
    @model_validator(mode="after")
    def timing(self):
        if self.before + self.after > self.duration:
            raise ValueError("La suma de los segundos anteriores y posteriores debe caber en la duración del clip.")
        self.model = "tiny"
        return self

    def window(self, event: float) -> tuple[float, float]:
        return event + self.after - self.duration, event + self.after


def overlap(first: tuple[float, float], second: tuple[float, float]) -> bool:
    common = min(first[1], second[1]) - max(first[0], second[0])
    return common > .4 * min(first[1] - first[0], second[1] - second[0])


@dataclass(frozen=True)
class CaptureCancellation:
    config: Event
    finished: Event

    def is_set(self) -> bool:
        return self.config.is_set() or self.finished.is_set()

    def wait(self, seconds: float) -> bool:
        return self.is_set() or self.finished.wait(seconds) or self.config.is_set()


@dataclass(frozen=True)
class Proposal:
    session: CaptureSession
    epoch: int
    origin: str
    signal: AudioSignal
    options: AutoOptions
    token: CaptureCancellation
    span: tuple[float, float]
    queued_at: float

    @property
    def strength(self):
        if self.signal.kind == "conversation":
            return .65 + self.signal.voice / 2
        return self.signal.voice + self.signal.intensity / 2


class AutoClip:
    def __init__(self, direct: DirectCapture, analysis: AnalysisQueue, shared: "AutoClip | None" = None):
        self.direct, self.analysis = direct, analysis
        self.library, self.media = direct.library, direct.media
        self.settings, self.db = direct.settings, direct.library.db
        self.root = self.settings.data_dir.resolve() / "autoclips"
        self.lock = RLock()
        self.review_lock = shared.review_lock if shared else RLock()
        self.render_lock = shared.render_lock if shared else RLock()
        self.pcm_lock = shared.pcm_lock if shared else RLock()
        self.quota_lock = shared.quota_lock if shared else RLock()
        self.shutdown_event, self.wake, self.cancel = Event(), Event(), Event()
        self.options = AutoOptions()
        self.stage, self.message = "disabled", None
        self.detected = self.filtered = self.skipped = 0
        self.last_attempt = float("-inf")
        self.deferred: list[Proposal] = []
        self.omissions: Counter[str] = Counter()
        self.filters: Counter[str] = Counter()
        self.audio_segments = self.audio_failures = self.transcriptions = self.generated = 0
        self.last_score = self.best_score = None
        self.last_error = None
        self.pending = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipzone-auto-candidate")
        self.saved = deque()
        self.saved_channel = None
        self.windows: deque[tuple[str, tuple[float, float]]] = deque(maxlen=80)
        if not shared:
            self.clean_files(self.db.list("autoclips"))
        self.monitor: Thread | None = None

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

    def progress(self) -> dict:
        with self.lock:
            return {"options": self.options.model_dump(), "stage": self.stage, "message": self.message,
                    "detected": self.detected, "filtered": self.filtered, "skipped": self.skipped,
                    "diagnostics": {"audio_segments": self.audio_segments, "audio_failures": self.audio_failures,
                                    "transcriptions": self.transcriptions, "generated": self.generated,
                                    "deferred": len(self.deferred), "last_score": self.last_score,
                                    "best_score": self.best_score, "last_error": self.last_error,
                                    "omissions": dict(self.omissions), "filters": dict(self.filters)}}

    def resources(self) -> dict:
        caps = capabilities(self.settings)
        return {**self.storage(), "detection_modes": get_args(DetectionMode),
                "vad": find_spec("webrtcvad") is not None,
                "whisper": all(caps["dependencies"].values()), "models": caps["models"]}

    def quota(self) -> CandidateStorage:
        return CandidateStorage.model_validate(self.db.get("settings", "autoclip_storage") or {"limit_gb": 5})

    def storage(self) -> dict:
        maximum = self.quota().limit_gb
        used = self.size()
        return {"bytes": used, "max_bytes": maximum * GB, "available_bytes": max(0, maximum * GB - used),
                "candidate_limit_gb": maximum}

    def configure_storage(self, storage: CandidateStorage) -> dict:
        with self.quota_lock:
            self.db.put("settings", {"id": "autoclip_storage", **storage.model_dump()})
            return self.storage()

    def status(self) -> dict:
        return {**self.progress(), **self.resources()}

    def check_options(self, options: AutoOptions) -> None:
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

    def apply_options(self, options: AutoOptions) -> None:
        with self.lock:
            if self.options != options:
                self.cancel.set()
                self.cancel = Event()
                self.options = options
                self.deferred.clear()
                self.last_attempt = float("-inf")
                self.stage = "waiting" if options.enabled else "disabled"
                self.message = None
                self.wake.set()
            if options.enabled and (self.monitor is None or not self.monitor.is_alive()):
                self.monitor = Thread(target=self.run, name="clipzone-auto-listen", daemon=True)
                self.monitor.start()

    def configure(self, options: AutoOptions) -> dict:
        self.check_options(options)
        self.apply_options(options)
        return self.status()

    def activity(self, token: Event | CaptureCancellation, stage: str, message: str | None = None) -> None:
        with self.lock:
            if not token.is_set():
                self.stage, self.message = stage, message

    def next_audio(self, previous: str | None) -> tuple[CaptureSession, int, Segment] | None:
        with self.direct.lock:
            session = self.direct.session
            if not session or session.finished.is_set() or session.state not in CAPTURE_STATES or not session.buffer.closed:
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
            try:
                self.drain()
                picked = self.next_audio(previous)
            except Exception:
                logger.exception("Falló la lectura del estado del búfer de AutoClipping.")
                self.error(token, "No se pudo consultar el búfer directo.")
                self.shutdown_event.wait(.5)
                continue
            if picked is None:
                with self.direct.lock:
                    session = self.direct.session
                    finished = not session or session.finished.is_set() or session.state not in CAPTURE_STATES
                    inactive = finished or not session.buffer.closed
                if inactive and not idle:
                    with self.lock:
                        if finished and not token.is_set():
                            self.deferred.clear()
                            self.activity(token, "waiting")
                        elif not self.pending and self.stage not in {"error", "waiting"}:
                            self.activity(token, "waiting")
                    idle = True
                self.shutdown_event.wait(.25)
                continue
            idle = False
            session, epoch, segment = picked
            cancellation = CaptureCancellation(token, session.finished)
            previous = str(segment.path)
            identity_now = (session.buffer.folder, epoch)
            try:
                if identity != identity_now or abs(end - segment.start) > .8:
                    detector = LiveDetector(options.sensitivity, options.detection_mode)
                    identity = identity_now
                end = segment.start + segment.duration
                data = self.pcm(["-i", str(segment.path)], duration=min(9, segment.duration), token=cancellation)
                with self.lock:
                    if data and not cancellation.is_set():
                        self.audio_segments += 1
                    if not self.pending:
                        message = self.message if data and self.stage != "waiting" else None
                        self.activity(cancellation, "listening", message if data else "Esperando segmentos con audio.")
                if data and not cancellation.is_set():
                    for signal in detector.feed(data, segment.start):
                        self.propose(session, epoch, signal, options, token)
            except Exception as exc:
                identity = None
                with self.lock:
                    if not cancellation.is_set():
                        self.audio_failures += 1
                        if self.stage != "error":
                            logger.exception("Falló el audio de AutoClipping para %s:%s.",
                                             session.source.platform, session.source.channel)
                self.error(cancellation, str(exc) if isinstance(exc, MediaError) else "No se pudo leer el audio del búfer.")
            finally:
                self.direct.release_segments(session, (segment,))

    def pcm(self, inputs: list[str], duration: float, start=0., cwd=None, token: CaptureCancellation | None = None) -> bytes:
        with self.pcm_lock:
            if token is not None and token.is_set():
                return b""
            command = [self.media.require("ffmpeg"), "-hide_banner", "-v", "error", "-nostdin",
                       "-protocol_whitelist", "file,pipe", *inputs, "-ss", f"{start:.6f}",
                       "-t", f"{duration:.6f}", "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
                       "-threads", "1", "-f", "s16le", "pipe:1"]
            deadline = monotonic() + 12
            with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=CREATE_NO_WINDOW, start_new_session=os.name != "nt") as process:
                try:
                    while True:
                        if token is not None and token.is_set():
                            return b""
                        try:
                            audio, errors = process.communicate(timeout=.2)
                            break
                        except subprocess.TimeoutExpired:
                            if monotonic() >= deadline:
                                raise
                finally:
                    terminate_tree(process)
        if process.returncode:
            details = errors.decode("utf-8", errors="replace").strip()
            raise MediaError(f"FFmpeg no pudo extraer el audio: {details[-600:]}" if details else
                             "FFmpeg no pudo extraer el audio del búfer.")
        return audio

    def propose(self, session: CaptureSession, epoch: int, signal: AudioSignal, options: AutoOptions, token: Event) -> None:
        origin = f"{session.buffer.folder.name}:{epoch}"
        span = options.window(signal.time)
        cancellation = CaptureCancellation(token, session.finished)
        with self.lock:
            if cancellation.is_set() or self.shutdown_event.is_set():
                return
            self.detected += 1
            channel = (session.source.platform, session.source.channel)
            if channel != self.saved_channel:
                self.saved_channel = channel
                self.last_attempt = float("-inf")
                self.deferred.clear()
                self.saved = deque(sorted(datetime.fromisoformat(row["created_at"]).timestamp()
                    for row in self.db.list("autoclips") if (row.get("platform"), row.get("channel")) == channel))
            proposal = Proposal(session, epoch, origin, signal, options, cancellation, span, monotonic())
            if self.limit(proposal):
                return
            # Conserva alternativas acústicas mientras se reúne el postroll o Whisper está ocupado.
            same = [item for item in self.deferred if item.origin == origin and abs(item.signal.time - signal.time) < 3]
            if same:
                previous = same[0]
                self.omit("nearby_signal")
                if previous.strength >= proposal.strength:
                    return
                self.deferred.remove(previous)
            self.deferred.append(proposal)
            if len(self.deferred) > DEFERRED_LIMIT:
                self.deferred.remove(min(self.deferred, key=lambda item: item.strength))
                self.omit("backlog_limit")
            self.drain()

    def omit(self, code: str) -> None:
        self.skipped += 1
        self.omissions[code] += 1

    def limit(self, proposal: Proposal) -> bool:
        clock = time()
        while self.saved and self.saved[0] <= clock - 3600:
            self.saved.popleft()
        if any(key == proposal.origin and overlap(previous, proposal.span) for key, previous in self.windows):
            self.omit("overlap")
        elif len(self.saved) >= proposal.options.per_hour:
            self.omit("hour_limit")
        elif self.saved and clock - self.saved[-1] < proposal.options.interval:
            self.omit("saved_interval")
        else:
            return False
        return True

    def drain(self) -> None:
        with self.lock:
            clock = monotonic()
            if self.pending is not None or clock - self.last_attempt < RETRY_DELAY or self.shutdown_event.is_set():
                return
            while self.deferred:
                proposal = max(self.deferred, key=lambda item: item.strength)
                self.deferred.remove(proposal)
                if proposal.token.is_set():
                    continue
                if clock - proposal.queued_at > DEFERRED_AGE:
                    self.omit("expired_signal")
                    continue
                if self.limit(proposal):
                    continue
                self.last_attempt = clock
                self.activity(proposal.token, "collecting")
                self.pending = self.executor.submit(self.process, proposal.session, proposal.epoch, proposal.origin,
                                                    proposal.signal, proposal.options, proposal.token, proposal.span)
                return

    def collect(self, session: CaptureSession, epoch: int, window: tuple[float, float], event: float,
                options: AutoOptions, token: CaptureCancellation, held: dict[Path, Segment]) -> tuple[float, float] | None:
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
                    raise LiveError("auto_buffer_budget", "El candidato excede el margen reservado del búfer temporal.")
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
                self.skip(token, "incomplete_buffer", "El búfer anterior o posterior no llegó a completarse.")
                return
            segments = tuple(held.values())
            if any(item.path.resolve() != item.path for item in segments):
                raise LiveError("auto_storage", "No se encontró un segmento temporal válido.")
            write_playlist(playlist, segments)
            inputs = ["-f", "concat", "-safe", "1", "-i", playlist.name]
            audio_start = max(span[0], signal.time - 14)
            if signal.kind == "conversation":
                audio_start = max(span[0], min(signal.time - 12, span[1] - 24))
            audio_end = min(span[1], audio_start + 24)
            sound = self.pcm(inputs, audio_end - audio_start, audio_start - segments[0].start, folder, token)
            if not sound:
                self.skip(token, "no_audio", "El candidato no contiene audio utilizable.")
                return
            transcript = {"words": []}
            if signal.kind in {"reaction", "conversation"} or signal.voice >= .45 or has_speech_context(sound):
                self.activity(token, "waiting_whisper")
                with TemporaryDirectory(prefix="clipzone-auto-") as temp:
                    audio, result = Path(temp) / "event.pcm", Path(temp) / "event.json"
                    audio.write_bytes(sound)
                    transcript = self.analysis.transcribe_live(audio, options.model, result, token,
                                                               on_start=lambda: self.activity(token, "transcribing"))
                with self.lock:
                    if transcript is not None and not token.is_set():
                        self.transcriptions += 1
            if transcript is None:
                self.skip(token, "whisper_cancelled", "El análisis del candidato se canceló.")
                return
            editorial = editorial_score(transcript, signal.time - audio_start, signal, options.detection_mode)
            filters = editorial.pop("filters")
            with self.lock:
                if not token.is_set():
                    self.last_score = editorial["score"]
                    self.best_score = max(self.best_score or 0, self.last_score)
            if not editorial["score"] or editorial["score"] < options.minimum_score:
                with self.lock:
                    if not token.is_set():
                        self.filtered += 1
                        self.filters.update(filters or ("under_threshold",))
                self.activity(token, "listening", f"Candidato filtrado ({editorial['score']}/100). {editorial['reason']}.")
                return
            if token.is_set():
                return
            self.activity(token, "saving")
            movie = self.root / f"{candidate_id}.mp4"
            with self.render_lock:
                if token.is_set():
                    return
                info = self.render(inputs, folder, movie, span[0] - segments[0].start, span[1] - span[0], token)
                with self.quota_lock, self.lock:
                    if not info or token.is_set():
                        return
                    if self.size() > self.quota().limit_gb * GB:
                        raise LiveError("auto_disk", "La cuota de candidatos está llena. Revisa los candidatos guardados.")
                    row = {**editorial, "id": candidate_id, "status": "pending", "created_at": now(),
                           "duration": info["duration"], "size": movie.stat().st_size, "model": options.model,
                           "platform": session.source.platform, "channel": session.source.channel, "quality": session.quality,
                           **({"channel_name": session.source.name} if session.source.name else {}),
                           "requested_seconds": options.duration, "video_id": None}
                    self.db.put("autoclips", row)
                    committed = True
                    self.saved.append(time())
                    self.windows.append((origin, span))
                    self.generated += 1
            self.activity(token, "listening", "Candidato guardado para revisión.")
        except LiveWhisperQueueTimeout as exc:
            self.skip(token, "whisper_queue_timeout", str(exc))
        except Exception as exc:
            expected = {"auto_disk": "candidate_storage", "auto_buffer_budget": "buffer_budget",
                        "auto_incomplete": "incomplete_render"}
            if not token.is_set() and isinstance(exc, LiveError) and exc.code in expected:
                logger.warning("Candidato omitido de %s:%s (%s): %s",
                               session.source.platform, session.source.channel, exc.code, exc)
                self.skip(token, expected[exc.code], str(exc))
            elif not token.is_set():
                logger.exception("Falló un candidato de AutoClipping para %s:%s.", session.source.platform, session.source.channel)
                message = str(exc) if isinstance(exc, (LiveError, MediaError, LiveWhisperError)) else "No se pudo completar el candidato. Consulta el registro del servidor."
                self.error(token, message)
        finally:
            self.remove_file(playlist)
            if not committed:
                self.remove_temporary(candidate_id)
            self.direct.release_segments(session, tuple(held.values()))
            with self.lock:
                self.pending = None

    def error(self, token: Event | CaptureCancellation, message: str) -> None:
        with self.lock:
            if not token.is_set():
                self.last_error = message
                self.activity(token, "error", message)

    def skip(self, token: CaptureCancellation, code: str, message: str) -> None:
        with self.lock:
            if not token.is_set():
                self.omit(code)
                self.activity(token, "skipped", message)

    def render(self, inputs, folder, movie, start, duration, token: CaptureCancellation) -> dict | None:
        budget = min(self.quota().limit_gb * GB - self.size(), (self.direct.disk_free() or 0) - MIN_FREE) - 1024**2
        if budget < MIN_CANDIDATE_BYTES:
            raise LiveError("auto_disk", "No hay espacio suficiente en el disco o en la cuota de candidatos de AutoClipping.")
        temporary = movie.with_suffix(".part")
        command = [self.media.require("ffmpeg"), "-hide_banner", "-v", "error", "-nostdin", "-y",
                   "-protocol_whitelist", "file,pipe", "-threads", "2", *inputs, "-ss", f"{start:.6f}",
                   "-t", f"{duration:.6f}", "-map", "0:V:0", "-map", "0:a:0", "-filter_threads", "1",
                   "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-threads:v", "2", "-preset", "veryfast",
                   "-crf", "21", "-maxrate", "8M", "-bufsize", "8M", "-pix_fmt", "yuv420p", "-c:a", "aac",
                   "-fs", str(budget), "-movflags", "+faststart", "-f", "mp4", str(temporary)]
        deadline = monotonic() + 105
        with TemporaryFile(mode="w+b") as errors, subprocess.Popen(
            command, cwd=folder, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=errors, creationflags=CREATE_NO_WINDOW, start_new_session=os.name != "nt",
        ) as process:
            try:
                while process.poll() is None:
                    if token.wait(.25):
                        return None
                    if monotonic() > deadline:
                        raise MediaError("El render de AutoClipping tardó demasiado.")
                if process.returncode:
                    errors.seek(0, os.SEEK_END)
                    errors.seek(max(0, errors.tell() - 1500))
                    details = errors.read().decode("utf-8", errors="replace").strip()
                    raise MediaError(f"No se pudo renderizar el candidato. {details}".strip())
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
                    live = {key: row[key] for key in ("platform", "channel", "quality", "requested_seconds")}
                    if row.get("channel_name"):
                        live["channel_name"] = row["channel_name"]
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
        if self.monitor:
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
    def status(slot: int = Query(0, ge=0, le=1), streamer: str | None = None):
        return app.state.multistream.auto_status(streamer, slot)

    @app.post("/api/live/auto/config")
    def configure(body: AutoFields, slot: int = Query(0, ge=0, le=1), streamer: str | None = None):
        return app.state.multistream.configure_auto(body, streamer, slot)

    @app.post("/api/live/auto/storage")
    def configure_storage(body: CandidateStorage):
        return app.state.autoclip.configure_storage(body)

    @app.get("/api/live/auto/candidates")
    def history():
        return [public(row) for index, row in enumerate(app.state.db.list("autoclips"))
                if index < 100 or row["status"] == "pending"]

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
