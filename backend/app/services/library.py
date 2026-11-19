"""Incorpora archivos locales y cargas HTTP con el mismo flujo de preparación."""
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

from ..config import Settings
from ..database import Database, now
from .jobs import JobQueue
from .media import MediaService

logger = logging.getLogger("clipzone.library")
SUPPORTED_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts", ".m2ts"}


@dataclass
class StagedVideo:
    id: str
    source: Path
    partial: Path
    thumbnail: Path
    committed: bool = False


class VideoLibrary:
    def __init__(self, settings: Settings, db: Database, media: MediaService, queue: JobQueue,
                 lock: Lock, active_uploads: set[str]):
        self.settings = settings
        self.db = db
        self.media = media
        self.queue = queue
        self.lock = lock
        self.active_uploads = active_uploads

    @contextmanager
    def stage(self, suffix: str):
        if suffix not in SUPPORTED_VIDEO:
            raise ValueError("Formato de vídeo no admitido.")
        identifier = uuid4().hex
        root = self.settings.data_dir
        source = root / "uploads" / (identifier + suffix)
        staged = StagedVideo(identifier, source, source.with_suffix(".part"),
                             root / "thumbnails" / f"{identifier}.jpg")
        with self.lock:
            self.active_uploads.add(identifier)
        try:
            yield staged
        finally:
            paths = [staged.partial]
            if not staged.committed:
                paths.extend([staged.source, staged.thumbnail])
            for path in paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("No se pudo retirar un archivo de importación %s.", path.name)
            with self.lock:
                self.active_uploads.discard(identifier)

    def finish(self, staged: StagedVideo, name: str, live: dict | None = None, candidate: dict | None = None) -> dict:
        metadata = self.media.probe(staged.partial)
        staged.partial.replace(staged.source)
        size = staged.source.stat().st_size
        self.media.thumbnail(staged.source, staged.thumbnail)
        # MP4 H.264 de 8 bits se reproduce directamente; el resto obtiene un proxy local.
        direct = (staged.source.suffix in {".mp4", ".m4v"} and metadata["codec"] == "h264"
                  and metadata["pixel_format"] in {"yuv420p", "yuvj420p"}
                  and metadata["audio_codec"] in (None, "aac", "mp3"))
        preview = staged.source if direct else self.settings.data_dir / "previews" / f"{staged.id}.mp4"
        video = {"id": staged.id, "name": name, "size": size, **metadata, "created_at": now(),
                 "source_path": str(staged.source), "preview_path": str(preview),
                 "thumbnail_path": str(staged.thumbnail), "preview_status": "ready" if direct else "processing"}
        command = None if direct else self.media.proxy_command(staged.source, preview)
        with self.lock:
            if live is None:
                self.db.put("videos", video)
            else:
                self.db.put_live_video(video, {**live, "id": staged.id, "name": name,
                                               "duration": video["duration"], "size": size}, candidate)
            staged.committed = True
            if command:
                try:
                    self.queue.submit(kind="preview", video_id=staged.id, command=command, output=preview,
                                      duration=video["duration"], title=f"Preparar {name}")
                except (RuntimeError, OSError):
                    logger.exception("No se pudo encolar la vista previa de %s.", staged.id)
                    video["preview_status"] = "failed"
                    self.db.put("videos", video)
        return video
