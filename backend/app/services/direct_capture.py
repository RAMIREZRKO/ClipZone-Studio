"""Captura directa de un canal y guardado de fragmentos desde el búfer circular."""
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, SimpleQueue
import logging
import os
from shutil import disk_usage
import subprocess
from threading import Event, RLock, Thread
from time import monotonic
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from ..config import Settings
from ..database import now
from .direct_buffer import PLAYLIST_NAME, DirectBuffer, Segment, clean_session, write_playlist
from .direct_source import QUALITY, DirectSource, StreamlinkSource, source_from_url, terminate_tree
from .library import VideoLibrary
from .media import CREATE_NO_WINDOW, MediaError
from .obs import LiveError

logger = logging.getLogger("clipzone.direct")
MIN_FREE = 128 * 1024**2
ACTIVE = {"connecting", "capturing", "reconnecting", "stopping"}
RETRY_DELAYS = (1, 3, 6)
SEGMENT_TIMEOUT = 25


class SourceRequest(BaseModel):
    url: str = Field(max_length=500)


class StartRequest(SourceRequest):
    quality: str = Field(max_length=25, pattern=rf"^{QUALITY.pattern}$")


class DirectSaveRequest(BaseModel):
    seconds: Literal[30, 60, 90, 120, 300]


@dataclass
class CaptureSession:
    source: DirectSource
    quality: str
    buffer: DirectBuffer
    state: str = "connecting"
    attempts: int = 0
    warning: str | None = None
    started: float = field(default_factory=monotonic)
    ended: float | None = None
    stop: Event = field(default_factory=Event)


class DirectCapture:
    def __init__(self, settings: Settings, library: VideoLibrary):
        self.settings = settings
        self.library = library
        self.media = library.media
        self.engine = StreamlinkSource()
        self.lock = RLock()
        self.session: CaptureSession | None = None
        self.worker: Thread | None = None
        self.saving = False
        self.root = settings.data_dir.resolve() / "direct-buffer"
        self.max_bytes = settings.direct_buffer_mb * 1024**2
        self.free_bytes: int | None = None
        for folder in self.root.iterdir():
            clean_session(folder)

    def inspect(self, url: str) -> dict:
        source = source_from_url(url)
        options = self.engine.inspect(source)
        return {"platform": source.platform, "channel": source.channel, "url": source.url,
                "live": bool(options), "qualities": options}

    def status(self) -> dict:
        with self.lock:
            session = self.session
            return {
                "installed": self.engine.available(), "state": session.state if session else "idle",
                "platform": session.source.platform if session else None, "url": session.source.url if session else None,
                "channel": session.source.channel if session else None, "quality": session.quality if session else None,
                "elapsed": round((session.ended or monotonic()) - session.started, 1) if session else 0,
                "buffer_seconds": round(session.buffer.seconds, 2) if session else 0,
                "bytes": session.buffer.bytes if session else 0, "max_bytes": self.max_bytes,
                "free_bytes": self.free_bytes if session and session.state in ACTIVE else self.disk_free(),
                "saving": self.saving, "retries": session.attempts if session else 0, "max_retries": len(RETRY_DELAYS),
                "message": session.warning if session else None,
            }

    def disk_free(self) -> int | None:
        try:
            return disk_usage(self.root).free
        except OSError:
            return None

    def start(self, body: StartRequest) -> dict:
        source = source_from_url(body.url)
        self.engine.require()
        self.media.require("ffmpeg")
        self.media.require("ffprobe")
        with self.lock:
            if self.saving or (self.worker and self.worker.is_alive()):
                raise LiveError("direct_busy", "Hay una captura o un guardado en curso. Detén la captura anterior para cambiar de canal.")
            free = self.disk_free()
            if free is None or free < MIN_FREE:
                raise LiveError("direct_disk", "Se necesitan al menos 128 MiB libres para iniciar el búfer.", 507)
            if self.session:
                clean_session(self.session.buffer.folder, self.session.buffer.pins)
            folder = self.root / uuid4().hex
            try:
                folder.mkdir()
            except OSError as exc:
                raise LiveError("direct_disk", "No se pudo crear la carpeta del búfer temporal.", 507) from exc
            self.free_bytes = free
            session = CaptureSession(source, body.quality, DirectBuffer(folder))
            self.session = session
            self.worker = Thread(target=self.run, args=(session,), name="clipzone-direct", daemon=True)
            self.worker.start()
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            if self.session and self.session.state in ACTIVE:
                self.session.state = "stopping"
                self.session.stop.set()
            return self.status()

    def transition(self, session: CaptureSession, state: str, message: str | None = None) -> None:
        with self.lock:
            if session.stop.is_set() and state not in {"stopped", "error"}:
                return
            session.state, session.warning = state, message
            if state not in ACTIVE:
                session.ended = monotonic()

    def run(self, session: CaptureSession) -> None:
        try:
            for generation in range(len(RETRY_DELAYS) + 1):
                if session.stop.is_set():
                    return
                if generation:
                    with self.lock:
                        session.attempts = generation
                    if session.stop.wait(RETRY_DELAYS[generation - 1]):
                        return
                try:
                    if not self.check_source(session, after_start=generation > 0):
                        return
                    self.capture_attempt(session, generation)
                except LiveError as exc:
                    if exc.code not in {"direct_network", "direct_timeout"}:
                        raise
                    if generation >= len(RETRY_DELAYS):
                        raise LiveError("direct_retries", "Se agotaron los intentos de reconexión. Puedes guardar el fragmento disponible.") from exc
                    self.transition(session, "reconnecting", "No se pudo conectar. Volviendo a comprobar el directo…")
                    continue
                if session.stop.is_set():
                    return
                # Una salida del productor también puede ser el fin natural de
                # la emisión. Consulta antes de gastar otro intento de conexión.
                self.transition(session, "reconnecting", "Se interrumpió la conexión. Comprobando el directo…")
                try:
                    if not self.check_source(session, after_start=True):
                        return
                except LiveError as exc:
                    if exc.code not in {"direct_network", "direct_timeout"}:
                        raise
                if generation >= len(RETRY_DELAYS):
                    raise LiveError("direct_retries", "Se agotaron los intentos de reconexión. Puedes guardar el fragmento disponible.")
        except LiveError as exc:
            if not session.stop.is_set():
                self.transition(session, "error", str(exc))
                logger.info("Captura directa: %s", exc.code)
        except (MediaError, OSError, subprocess.SubprocessError):
            if not session.stop.is_set():
                self.transition(session, "error", "Se interrumpió FFmpeg o el almacenamiento temporal. Puedes guardar el fragmento disponible.")
                logger.exception("Falló un proceso de captura directa.")
        finally:
            if session.stop.is_set():
                self.transition(session, "stopped", None)

    def check_source(self, session: CaptureSession, after_start: bool) -> bool:
        qualities = self.engine.inspect(session.source, session.stop)
        if session.stop.is_set():
            return False
        if not qualities:
            message = "La transmisión finalizó. Puedes guardar el fragmento disponible." if after_start else "El canal no está en directo."
            self.transition(session, "ended", message)
            return False
        if session.quality not in qualities:
            raise LiveError("direct_quality", "La calidad elegida no está disponible. Comprueba el directo y elige otra.", 422)
        return True

    def ffmpeg_command(self, generation: int) -> list[str]:
        return [
            self.media.require("ffmpeg"), "-hide_banner", "-v", "error", "-nostdin", "-y",
            "-protocol_whitelist", "file,pipe", "-fflags", "+genpts+discardcorrupt", "-i", "pipe:0",
            "-map", "0:V:0", "-map", "0:a:0?", "-c", "copy", "-f", "segment",
            "-segment_time", "2", "-segment_format", "matroska", "-reset_timestamps", "1",
            "-segment_list_type", "csv", "-segment_list", "pipe:1", DirectBuffer.pattern(generation),
        ]

    def capture_attempt(self, session: CaptureSession, generation: int) -> None:
        producer = self.engine.open(session.source, session.quality)
        consumer = reader = None
        messages = SimpleQueue()
        try:
            consumer = subprocess.Popen(self.ffmpeg_command(generation), cwd=session.buffer.folder,
                                        stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        creationflags=CREATE_NO_WINDOW, start_new_session=os.name != "nt")
            stdout = consumer.stdout

            def read_segments():
                try:
                    for line in stdout:
                        messages.put(line)
                finally:
                    messages.put(None)

            producer.stdout.close()
            reader = Thread(target=read_segments, name="clipzone-segments", daemon=True)
            reader.start()
            last_segment = monotonic()
            next_check = last_segment
            while not session.stop.is_set():
                try:
                    line = messages.get(timeout=.25)
                    if line is None:
                        break
                    if self.publish(session, generation, line):
                        last_segment = monotonic()
                except Empty:
                    pass
                clock = monotonic()
                if clock >= next_check:
                    self.maintain(session)
                    next_check = clock + .75
                if clock - last_segment > SEGMENT_TIMEOUT:
                    break
        finally:
            try:
                if producer.stdout and not producer.stdout.closed:
                    producer.stdout.close()
                terminate_tree(producer)
            finally:
                if consumer is not None:
                    try:
                        consumer.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        terminate_tree(consumer)
                    if reader is not None:
                        reader.join(timeout=1)
                    consumer.stdout.close()
                while not messages.empty():
                    line = messages.get_nowait()
                    if line is not None:
                        self.publish(session, generation, line)
                with self.lock:
                    session.buffer.discard_incomplete(generation)
                self.maintain(session)

    def publish(self, session: CaptureSession, generation: int, line: bytes) -> bool:
        with self.lock:
            if session.buffer.accept(line, generation):
                self.transition(session, "capturing")
                return True
            return False

    def maintain(self, session: CaptureSession) -> None:
        with self.lock:
            free = self.disk_free()
            buffer = session.buffer
            buffer.reap()
            if free is None:
                raise LiveError("direct_disk", "No se pudo consultar el disco del búfer.", 507)
            measured = buffer.measure()
            maximum = min(self.max_bytes, max(0, measured + free - MIN_FREE))
            size = buffer.enforce_bytes(maximum) if measured > maximum else measured
            self.free_bytes = self.disk_free()
            if size > self.max_bytes or self.free_bytes is None or self.free_bytes < MIN_FREE:
                raise LiveError("direct_disk", "La captura se detuvo por falta de espacio en el búfer o en el disco.", 507)

    def save(self, seconds: int) -> tuple[dict, dict]:
        with self.lock:
            if self.saving:
                raise LiveError("direct_saving", "Ya se está guardando un fragmento.")
            if not self.session or not self.session.buffer.closed:
                raise LiveError("direct_empty", "Aún no hay segmentos completos en el búfer.")
            session = self.session
            segments = session.buffer.snapshot(seconds)
            self.saving = True
        try:
            return self.save_snapshot(session, segments, seconds)
        except OSError as exc:
            raise LiveError("direct_storage", "No se pudo escribir el fragmento. Revisa el espacio y los permisos.", 507) from exc
        finally:
            with self.lock:
                session.buffer.release(segments)
                self.saving = False

    def release_segments(self, session: CaptureSession, segments: tuple[Segment, ...]) -> None:
        with self.lock:
            session.buffer.release(segments)
            if self.session is not session:
                clean_session(session.buffer.folder, session.buffer.pins)

    def save_snapshot(self, session: CaptureSession, segments: tuple[Segment, ...], seconds: int) -> tuple[dict, dict]:
        folder = session.buffer.folder
        playlist = folder / PLAYLIST_NAME
        estimate = sum(segment.duration for segment in segments)
        if any(segment.path.resolve() != segment.path for segment in segments):
            raise LiveError("direct_storage", "La ruta de un segmento temporal ya no es válida.", 422)
        size = sum(segment.path.stat().st_size for segment in segments)
        if size > self.settings.max_upload_bytes:
            raise LiveError("direct_size", "El fragmento supera el límite de importación de ClipZone.", 413)
        if (self.disk_free() or 0) < size + MIN_FREE:
            raise LiveError("direct_disk", "Falta espacio para guardar el fragmento. El búfer y los clips guardados se conservan.", 507)
        write_playlist(playlist, segments)
        captured_at = now()
        platform = {"kick": "Kick", "twitch": "Twitch"}.get(session.source.platform, "Live")
        capture = {"method": "direct", "platform": session.source.platform, "quality": session.quality,
                   "requested_seconds": seconds, "captured_at": captured_at}
        try:
            for suffix, container in ((".mp4", "mp4"), (".mkv", "matroska")):
                with self.library.stage(suffix) as staged:
                    trim = len(segments) == 1 and estimate > seconds + .06
                    if not self.mux(playlist, staged.partial.resolve(), container, seconds, estimate - seconds if trim else 0):
                        continue
                    if staged.partial.stat().st_size > self.settings.max_upload_bytes:
                        raise LiveError("direct_size", "El fragmento supera el límite de importación de ClipZone.", 413)
                    metadata = self.media.probe(staged.partial)
                    if not .08 <= metadata["duration"] <= min(seconds, estimate) + 1:
                        raise LiveError("direct_duration", "La duración del fragmento es irregular. Espera a que el búfer reciba segmentos estables.", 422)
                    timestamp = captured_at.partition(".")[0].replace(":", "-").replace("T", " ")
                    video = self.library.finish(staged, f"{platform} · {session.source.channel} · {timestamp}{suffix}", capture)
                    return {**capture, "id": video["id"], "name": video["name"], "duration": video["duration"], "size": video["size"]}, video
            raise LiveError("direct_mux", "FFmpeg no pudo unir los segmentos. Espera a que llegue un fragmento estable.", 422)
        finally:
            playlist.unlink(missing_ok=True)

    def mux(self, playlist: Path, output: Path, container: str, seconds: int, offset: float) -> bool:
        command = [self.media.require("ffmpeg"), "-hide_banner", "-v", "error", "-xerror", "-nostdin", "-y",
                   "-protocol_whitelist", "file,pipe", "-f", "concat", "-safe", "1", "-i", playlist.name,
                   "-map", "0:V:0", "-map", "0:a:0?"]
        if offset > 0:
            command += ["-ss", f"{offset:.6f}", "-t", str(seconds), "-c:v", "libx264", "-threads:v", "2",
                        "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac"]
        else:
            command += ["-c", "copy"]
        if container == "mp4":
            command += ["-movflags", "+faststart"]
        command += ["-avoid_negative_ts", "make_zero", "-f", container, str(output)]
        try:
            result = subprocess.run(command, cwd=playlist.parent, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    creationflags=CREATE_NO_WINDOW, timeout=90 if offset > 0 else 30)
        except subprocess.TimeoutExpired as exc:
            raise LiveError("direct_save_timeout", "El guardado tardó demasiado. Puedes intentarlo de nuevo.", 504) from exc
        return result.returncode == 0

    def shutdown(self) -> None:
        self.stop()
        if self.worker:
            self.worker.join(timeout=12)
        with self.lock:
            if self.session and not self.saving and not (self.worker and self.worker.is_alive()):
                clean_session(self.session.buffer.folder)

