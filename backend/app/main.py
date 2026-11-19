from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from typing import Literal
from urllib.parse import quote
import asyncio
import logging
import mimetypes
import re
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .database import Database
from .models import ClipRequest
from .services.media import MediaError, MediaService
from .services.caption_layers import CaptionLayerRequest, CaptionLayers
from .services.jobs import JobQueue
from .services.direct_capture import DirectCapture
from .services.library import SUPPORTED_VIDEO, VideoLibrary
from .services.live import LiveCapture, register_live
from .services.analysis import AnalysisQueue
from .services.storage import ID, Storage, register_storage
from .ai.routes import register_ai
from .ai.models import capabilities
from .captions import CaptionSegment, clip_captions, register_captions
from .composition import CAPTION_RENDER_VERSION, ass_script, graphic_ass, subtitle_sidecar
from .campaigns import asset_file, register_campaigns
from .ai.model_files import ModelDownloads

logger = logging.getLogger("clipzone")
ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8000", "http://localhost:8000"}


def public_video(video: dict) -> dict:
    result = {k: v for k, v in video.items() if not k.endswith("_path")}
    result["preview_url"] = f"/api/videos/{video['id']}/preview" if video["preview_status"] == "ready" else None
    result["thumbnail_url"] = f"/api/videos/{video['id']}/thumbnail"
    return result


def public_job(job: dict) -> dict:
    result = {k: v for k, v in job.items() if k not in {"output_path", "sidecar_cues"}}
    result["preview_url"] = f"/api/jobs/{job['id']}/preview" if job["status"] == "completed" else None
    result["download_url"] = f"/api/jobs/{job['id']}/download" if job["status"] == "completed" and job["kind"] != "draft" else None
    if job["status"] == "completed" and job["kind"] == "export" and job.get("sidecar_cues"):
        result["subtitles"] = {kind: f"/api/jobs/{job['id']}/subtitles.{kind}" for kind in ("srt", "vtt")}
    return result


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.prepare()
        app.state.db = Database(settings.data_dir / "clipzone.sqlite3")
        app.state.storage = Storage(app.state.db, settings.data_dir, settings.model_dir)
        app.state.media = MediaService(settings)
        app.state.caption_layers = CaptionLayers(app.state.media)
        app.state.queue = JobQueue(app.state.db)
        app.state.analysis_queue = AnalysisQueue(app.state.db, settings)
        app.state.model_downloads = ModelDownloads(settings.model_dir, settings.data_dir / "whisper-downloads.log")
        app.state.export_lock = Lock()
        app.state.active_uploads = set()
        app.state.library = VideoLibrary(settings, app.state.db, app.state.media, app.state.queue,
                                         app.state.export_lock, app.state.active_uploads)
        app.state.live = LiveCapture(settings, app.state.library)
        app.state.direct = DirectCapture(settings, app.state.library)
        # Archivos parciales nunca se muestran como vídeos importados.
        for path in (settings.data_dir / "uploads").glob("*.part"):
            if ID.fullmatch(path.stem):
                try:
                    app.state.storage.path(path, "uploads").unlink(missing_ok=True)
                except (ValueError, OSError):
                    logger.warning("Un archivo parcial quedó pendiente de limpieza.")
        yield
        await asyncio.to_thread(app.state.direct.shutdown)
        await asyncio.to_thread(app.state.analysis_queue.shutdown)
        await asyncio.to_thread(app.state.queue.shutdown)
        await asyncio.to_thread(app.state.model_downloads.shutdown)

    app = FastAPI(title="ClipZone Studio", version="0.3.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=sorted(ORIGINS), allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        # Protege las operaciones locales frente a formularios de sitios ajenos.
        origin = request.headers.get("origin")
        same_origin = f"{request.url.scheme}://{request.url.netloc}"
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in ORIGINS and origin != same_origin:
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
        return {"status": "ok" if all(dependencies.values()) else "missing_dependencies", "version": app.version,
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
        if suffix not in SUPPORTED_VIDEO:
            raise HTTPException(415, "Formato no admitido. Usa MP4, MOV, MKV, WebM, AVI, M4V, MTS o M2TS.")
        library: VideoLibrary = app.state.library
        name = re.split(r"[/\\]", file.filename or "Vídeo")[-1]
        size = 0
        try:
            with library.stage(suffix) as staged:
                with staged.partial.open("wb") as output:
                    while chunk := await file.read(4 * 1024 * 1024):
                        size += len(chunk)
                        if size > settings.max_upload_bytes:
                            raise HTTPException(413, "El vídeo supera el límite local de importación.")
                        await asyncio.to_thread(output.write, chunk)
                if not size:
                    raise HTTPException(422, "El archivo está vacío.")
                video = await asyncio.to_thread(library.finish, staged, name)
                return public_video(video)
        finally:
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

    def render_captions(body: ClipRequest):
        options = body.captions
        if not options or not (options.enabled or options.sidecars):
            return []
        track = app.state.db.get("caption_tracks", body.video_id)
        if not track or track["revision"] != options.revision:
            raise HTTPException(409, "La pista de subtítulos cambió o no se ha guardado. Guárdala y vuelve a intentar.")
        segments = [CaptionSegment.model_validate(segment) for segment in track["segments"]]
        return clip_captions(segments, body.start, body.end, options.language)

    @app.post("/api/captions/layer")
    def live_caption_layer(body: CaptionLayerRequest):
        return app.state.caption_layers.page(body)

    def caption_cache_version(body: ClipRequest) -> dict:
        return {"caption_render_version": CAPTION_RENDER_VERSION} if body.captions and body.captions.enabled else {}

    def enqueue_clip(body: ClipRequest, provenance: dict | None = None, kind: str = "export"):
        video = find_video(body.video_id)
        if body.end > video["duration"] + 0.01:
            raise HTTPException(422, "El final del clip supera la duración del vídeo.")
        if not Path(video["source_path"]).is_file():
            raise HTTPException(404, "El archivo original ya no está disponible.")
        output = settings.data_dir / ("drafts" if kind == "draft" else "exports") / f"{uuid4().hex}.mp4"
        cues = render_captions(body)
        auxiliary = {}
        if cues and body.captions.enabled:
            auxiliary["overlay.ass"] = ass_script(cues, body.captions.style, body.dimensions(), body.safe_top, body.safe_bottom)
        layers = []
        duration = body.end - body.start
        for index, layer in enumerate(body.graphics):
            end = min(layer.end or duration, duration)
            if layer.start >= end or layer.opacity == 0:
                continue
            if layer.kind == "image" and layer.asset_id:
                layers.append((layer, asset_file(app.state.db, settings, layer.asset_id)))
            elif layer.kind == "text" and layer.text.strip():
                name = f"graphic{index}.ass"
                auxiliary[name] = graphic_ass(layer, body.dimensions(), end)
                layers.append((layer, name))
        command = app.state.media.render_command(Path(video["source_path"]), output, body,
                                                   use_ass="overlay.ass" in auxiliary, layers=layers)
        sidecars = [{"start": cue["start"], "end": cue["end"], "text": cue["text"]} for cue in cues] if cues and body.captions.sidecars and kind == "export" else None
        job = app.state.queue.submit(kind=kind, video_id=video["id"], command=command, output=output,
                                     duration=body.end - body.start, title=body.title.strip() or "Mi clip",
                                     settings={**body.model_dump(mode="json"), **(provenance or {}), **caption_cache_version(body)},
                                     auxiliary=auxiliary, sidecar_cues=sidecars)
        return public_job(job)

    @app.post("/api/clips", status_code=202)
    def create_clip(body: ClipRequest):
        with app.state.export_lock:
            if sum(j["status"] in ("queued", "running") for j in app.state.db.list("jobs")) >= 20:
                raise HTTPException(429, "Hay 20 trabajos pendientes. Espera a que terminen.")
            return enqueue_clip(body)

    @app.post("/api/clips/preview", status_code=202)
    def create_preview(body: ClipRequest):
        with app.state.export_lock:
            find_video(body.video_id)
            if body.captions is not None:
                render_captions(body)
            pending = 0
            options = {**body.model_dump(mode="json", exclude={"title"}), **caption_cache_version(body)}
            for job in app.state.db.list("jobs"):
                active = job["status"] in ("queued", "running")
                pending += active
                if job["kind"] != "draft" or job["video_id"] != body.video_id:
                    continue
                previous = {key: value for key, value in job["settings"].items() if key != "title"}
                if previous == options and (active or (
                    job["status"] == "completed" and Path(job["output_path"]).is_file()
                )):
                    return public_job(job)
            if pending >= 20:
                raise HTTPException(429, "Hay 20 trabajos pendientes. Espera a que terminen.")
            return enqueue_clip(body, kind="draft")

    register_ai(app, settings, find_video, enqueue_clip, public_job)
    register_captions(app, find_video)
    register_campaigns(app, settings)
    register_storage(app)
    register_live(app, public_video)

    @app.get("/api/jobs")
    def jobs():
        return [public_job(j) for j in app.state.db.list("jobs")]

    @app.get("/api/jobs/{identifier}")
    def job_status(identifier: str):
        return public_job(find_job(identifier))

    @app.post("/api/jobs/{identifier}/cancel")
    def cancel_job(identifier: str):
        with app.state.export_lock:
            find_job(identifier)
            return public_job(app.state.queue.cancel(identifier))

    def job_file(identifier: str, download: bool):
        job = find_job(identifier)
        if download and job["kind"] == "draft":
            raise HTTPException(404, "Exporta el clip para descargarlo.")
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

    @app.get("/api/jobs/{identifier}/subtitles.{kind}")
    def download_subtitles(identifier: str, kind: Literal["srt", "vtt"]):
        job = find_job(identifier)
        if job["status"] != "completed" or job["kind"] != "export" or not job.get("sidecar_cues"):
            raise HTTPException(404, "No hay subtítulos descargables en esta exportación.")
        title = re.sub(r"[^\w -]", "", job["title"]).strip()[:80] or "clipzone"
        headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(title)}.{kind}"}
        return Response(subtitle_sidecar(job["sidecar_cues"], kind), headers=headers,
                        media_type="text/vtt" if kind == "vtt" else "application/x-subrip; charset=utf-8")

    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    else:
        @app.get("/")
        def root():
            return {"message": "ClipZone Studio API. Compila frontend/ o abre http://127.0.0.1:5173.", "docs": "/docs"}

    return app


app = create_app()
