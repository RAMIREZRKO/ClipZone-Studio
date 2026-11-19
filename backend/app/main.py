from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
import asyncio
import logging
import mimetypes
import re
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .database import Database, now
from .models import ClipRequest
from .services.media import MediaError, MediaService
from .services.jobs import JobQueue
from .services.analysis import AnalysisQueue
from .ai.routes import register_ai
from .ai.models import capabilities

logger = logging.getLogger("clipzone")
SUPPORTED = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts", ".m2ts"}
ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8000", "http://localhost:8000"}


def public_video(video: dict) -> dict:
    result = {k: v for k, v in video.items() if not k.endswith("_path")}
    result["preview_url"] = f"/api/videos/{video['id']}/preview" if video["preview_status"] == "ready" else None
    result["thumbnail_url"] = f"/api/videos/{video['id']}/thumbnail"
    return result


def public_job(job: dict) -> dict:
    result = {k: v for k, v in job.items() if k != "output_path"}
    result["preview_url"] = f"/api/jobs/{job['id']}/preview" if job["status"] == "completed" else None
    result["download_url"] = f"/api/jobs/{job['id']}/download" if job["status"] == "completed" else None
    return result


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.prepare()
        app.state.db = Database(settings.data_dir / "clipzone.sqlite3")
        app.state.media = MediaService(settings)
        app.state.queue = JobQueue(app.state.db)
        app.state.analysis_queue = AnalysisQueue(app.state.db, settings)
        app.state.export_lock = Lock()
        # Archivos parciales nunca se muestran como vídeos importados.
        for path in (settings.data_dir / "uploads").glob("*.part"):
            path.unlink(missing_ok=True)
        yield
        await asyncio.to_thread(app.state.analysis_queue.shutdown)
        await asyncio.to_thread(app.state.queue.shutdown)

    app = FastAPI(title="ClipZone Studio", version="0.2.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=sorted(ORIGINS), allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        # Protege las operaciones locales frente a formularios de sitios ajenos.
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in ORIGINS:
            return JSONResponse({"detail": "Origen no autorizado."}, status_code=403)
        return await call_next(request)

    @app.exception_handler(MediaError)
    async def media_error(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def find_video(identifier: str) -> dict:
        video = app.state.db.get("videos", identifier)
        if not video:
            raise HTTPException(404, "No se encontró el vídeo.")
        return video

    def find_job(identifier: str) -> dict:
        job = app.state.db.get("jobs", identifier)
        if not job:
            raise HTTPException(404, "No se encontró la exportación.")
        return job

    @app.get("/api/health")
    def health():
        dependencies = {name: bool(settings.binary(name)) for name in ("ffmpeg", "ffprobe")}
        return {"status": "ok" if all(dependencies.values()) else "missing_dependencies", "version": "0.2.0",
                "dependencies": dependencies, "ai_enabled": capabilities(settings)["ready"], "max_upload_bytes": settings.max_upload_bytes}

    @app.get("/api/videos")
    def videos():
        return [public_video(v) for v in app.state.db.list("videos")]

    @app.post("/api/videos", status_code=201)
    async def upload(file: UploadFile):
        media: MediaService = app.state.media
        media.require("ffmpeg")
        media.require("ffprobe")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUPPORTED:
            raise HTTPException(415, "Formato no admitido. Usa MP4, MOV, MKV, WebM, AVI, M4V, MTS o M2TS.")
        identifier = uuid4().hex
        target = settings.data_dir / "uploads" / f"{identifier}{suffix}"
        partial = target.with_suffix(".part")
        thumbnail = settings.data_dir / "thumbnails" / f"{identifier}.jpg"
        size = 0
        saved = False
        try:
            with partial.open("wb") as output:
                while chunk := await file.read(4 * 1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(413, "El vídeo supera el límite local de importación.")
                    await asyncio.to_thread(output.write, chunk)
            if not size:
                raise HTTPException(422, "El archivo está vacío.")
            metadata = await asyncio.to_thread(media.probe, partial)
            partial.replace(target)
            await asyncio.to_thread(media.thumbnail, target, thumbnail)
            # MP4 H.264 de 8 bits se reproduce directamente; el resto obtiene un proxy local.
            direct = (suffix in {".mp4", ".m4v"} and metadata["codec"] == "h264"
                      and metadata["pixel_format"] in {"yuv420p", "yuvj420p"} and metadata["audio_codec"] in (None, "aac", "mp3"))
            preview = target if direct else settings.data_dir / "previews" / f"{identifier}.mp4"
            video = {"id": identifier, "name": re.split(r"[/\\]", file.filename or "Vídeo")[-1], "size": size,
                     **metadata, "created_at": now(), "source_path": str(target), "preview_path": str(preview),
                     "thumbnail_path": str(thumbnail), "preview_status": "ready" if direct else "processing"}
            if not direct:
                command = media.proxy_command(target, preview)
            app.state.db.put("videos", video)
            saved = True
            if not direct:
                app.state.queue.submit(kind="preview", video_id=identifier, command=command, output=preview,
                                       duration=video["duration"], title=f"Preparar {video['name']}")
            return public_video(video)
        finally:
            partial.unlink(missing_ok=True)
            if not saved:
                target.unlink(missing_ok=True)
                thumbnail.unlink(missing_ok=True)
            await file.close()

    @app.get("/api/videos/{identifier}/preview")
    def video_preview(identifier: str):
        video = find_video(identifier)
        if video["preview_status"] != "ready" or not Path(video["preview_path"]).is_file():
            raise HTTPException(409, "La previsualización todavía no está disponible.")
        return FileResponse(video["preview_path"], media_type=mimetypes.guess_type(video["preview_path"])[0] or "video/mp4")

    @app.get("/api/videos/{identifier}/thumbnail")
    def video_thumbnail(identifier: str):
        video = find_video(identifier)
        if not Path(video["thumbnail_path"]).is_file():
            raise HTTPException(404, "Sin miniatura.")
        return FileResponse(video["thumbnail_path"], media_type="image/jpeg")

    def enqueue_clip(body: ClipRequest, provenance: dict | None = None):
        video = find_video(body.video_id)
        if body.end > video["duration"] + 0.01:
            raise HTTPException(422, "El final del clip supera la duración del vídeo.")
        if not Path(video["source_path"]).is_file():
            raise HTTPException(404, "El archivo original ya no está disponible.")
        output = settings.data_dir / "exports" / f"{uuid4().hex}.mp4"
        command = app.state.media.render_command(Path(video["source_path"]), output, body)
        job = app.state.queue.submit(kind="export", video_id=video["id"], command=command, output=output,
                                     duration=body.end - body.start, title=body.title.strip() or "Mi clip",
                                     settings={**body.model_dump(mode="json"), **(provenance or {})})
        return public_job(job)

    @app.post("/api/clips", status_code=202)
    def create_clip(body: ClipRequest):
        with app.state.export_lock:
            if sum(j["status"] in ("queued", "running") for j in app.state.db.list("jobs")) >= 20:
                raise HTTPException(429, "Hay 20 trabajos pendientes. Espera a que terminen.")
            return enqueue_clip(body)

    register_ai(app, settings, find_video, enqueue_clip, public_job)

    @app.get("/api/jobs")
    def jobs():
        return [public_job(j) for j in app.state.db.list("jobs")]

    @app.get("/api/jobs/{identifier}")
    def job_status(identifier: str):
        return public_job(find_job(identifier))

    @app.post("/api/jobs/{identifier}/cancel")
    def cancel_job(identifier: str):
        find_job(identifier)
        return public_job(app.state.queue.cancel(identifier))

    def job_file(identifier: str, download: bool):
        job = find_job(identifier)
        if job["status"] != "completed":
            raise HTTPException(409, "La exportación aún no está lista.")
        if not Path(job["output_path"]).is_file():
            raise HTTPException(404, "El archivo exportado ya no está disponible.")
        title = re.sub(r"[^\w -]", "", job["title"]).strip()[:80] or "clipzone"
        return FileResponse(job["output_path"], media_type="video/mp4", filename=f"{title}.mp4" if download else None)

    @app.get("/api/jobs/{identifier}/preview")
    def job_preview(identifier: str):
        return job_file(identifier, False)

    @app.get("/api/jobs/{identifier}/download")
    def job_download(identifier: str):
        return job_file(identifier, True)

    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    else:
        @app.get("/")
        def root():
            return {"message": "ClipZone Studio API. Compila frontend/ o abre http://127.0.0.1:5173.", "docs": "/docs"}

    return app


app = create_app()
