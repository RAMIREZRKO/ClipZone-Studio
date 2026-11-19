"""API de análisis y generación múltiple; ningún endpoint descarga modelos."""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from .models import capabilities
from ..models import AnalysisRequest, BatchRequest, ClipRequest


def summary(item: dict) -> dict:
    return {k: v for k, v in item.items() if k != "result"}


def register_ai(app, settings, find_video, enqueue_clip, public_job):
    router = APIRouter(prefix="/api", tags=["IA local"])

    def find_analysis(identifier):
        item = app.state.db.get("analyses", identifier)
        if not item:
            raise HTTPException(404, "No se encontró el análisis.")
        return item

    @router.get("/ai/capabilities")
    def available():
        return capabilities(settings)

    @router.get("/videos/{identifier}/analyses")
    def analyses(identifier: str):
        find_video(identifier)
        return [summary(a) for a in app.state.db.list("analyses") if a["video_id"] == identifier]

    @router.post("/videos/{identifier}/analyses", status_code=202)
    def analyze(identifier: str, body: AnalysisRequest):
        video = find_video(identifier)
        if not video["has_audio"]:
            raise HTTPException(422, "Este vídeo no tiene audio. La detección utiliza el habla transcrita.")
        if body.min_duration > video["duration"]:
            raise HTTPException(422, "La duración mínima supera la duración del vídeo.")
        if not Path(video["source_path"]).is_file():
            raise HTTPException(404, "El archivo original ya no está disponible.")
        available = capabilities(settings)
        if not all(available["dependencies"].values()):
            raise HTTPException(503, "Instala Whisper local con scripts/setup-ai.ps1 antes de analizar.")
        if not any(m["id"] == body.model and m["installed"] for m in available["models"]):
            raise HTTPException(409, f"El modelo {body.model} no está instalado. Ejecuta scripts/setup-ai.ps1 -Model {body.model}.")
        try:
            return summary(app.state.analysis_queue.submit(video, body))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/analyses/{identifier}")
    def analysis_status(identifier: str):
        return summary(find_analysis(identifier))

    @router.get("/analyses/{identifier}/result")
    def analysis_result(identifier: str):
        item = find_analysis(identifier)
        if item["status"] != "completed":
            raise HTTPException(409, "El análisis todavía no ha terminado.")
        return item["result"]

    @router.post("/analyses/{identifier}/cancel")
    def cancel_analysis(identifier: str):
        find_analysis(identifier)
        return summary(app.state.analysis_queue.cancel(identifier))

    @router.post("/clips/batch", status_code=202)
    def batch(body: BatchRequest):
        analysis = find_analysis(body.analysis_id)
        if analysis["status"] != "completed":
            raise HTTPException(409, "Espera a que termine el análisis antes de generar clips.")
        lookup = {m["id"]: m for m in analysis["result"]["moments"]}
        if any(identifier not in lookup for identifier in body.moment_ids):
            raise HTTPException(422, "La selección incluye un momento que no pertenece a este análisis.")
        options = body.model_dump(exclude={"analysis_id", "moment_ids"})
        clips = [ClipRequest(**options, video_id=analysis["video_id"], start=lookup[i]["start"], end=lookup[i]["end"],
                             title=lookup[i]["title"] or "Momento destacado") for i in body.moment_ids]
        video = find_video(analysis["video_id"])
        if not Path(video["source_path"]).is_file():
            raise HTTPException(404, "El archivo original ya no está disponible.")
        if any(c.end > video["duration"] + .01 for c in clips):
            raise HTTPException(422, "Los intervalos ya no coinciden con el vídeo original.")
        with app.state.export_lock:
            pending = sum(j["status"] in {"queued", "running"} for j in app.state.db.list("jobs"))
            if pending + len(clips) > 20:
                raise HTTPException(429, "La selección supera los 20 trabajos pendientes. Reduce el lote o espera.")
            # Valida el ejecutable antes de encolar cualquier archivo del lote.
            app.state.media.require("ffmpeg")
            jobs = [enqueue_clip(c, {"analysis_id": analysis["id"], "moment_id": i, "score": lookup[i]["score"]})
                    for c, i in zip(clips, body.moment_ids)]
        return {"jobs": jobs, "count": len(jobs)}

    app.include_router(router)
