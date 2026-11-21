"""Análisis, generación múltiple e instalación explícita de modelos locales."""
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException
from .models import capabilities
from ..campaigns import asset_file
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
        return {**capabilities(settings), "downloads": app.state.model_downloads.statuses(), "device": "cpu"}

    @router.post("/ai/models/{model}/download", status_code=202)
    def download(model: Literal["tiny", "base", "small"]):
        try:
            return app.state.model_downloads.start(model)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/ai/models/{model}/cancel")
    def cancel_download(model: Literal["tiny", "base", "small"]):
        app.state.model_downloads.cancel(model)
        return app.state.model_downloads.statuses().get(model)

    @router.get("/videos/{identifier}/analyses")
    def analyses(identifier: str):
        find_video(identifier)
        return [summary(a) for a in app.state.db.list("analyses") if a["video_id"] == identifier]

    @router.post("/videos/{identifier}/analyses", status_code=202)
    def analyze(identifier: str, body: AnalysisRequest):
        video = find_video(identifier)
        if not video["has_audio"]:
            raise HTTPException(422, "Este vídeo no tiene audio. La detección utiliza el habla transcrita.")
        if body.transcript_window is not None:
            start, end = body.transcript_window
            if body.model != "small" or not 0 <= start < end <= video["duration"] + .001 or not .1 <= end - start <= 3600:
                raise HTTPException(422, "Selecciona un tramo válido para retranscribirlo con Whisper Small.")
        elif body.min_duration > video["duration"]:
            raise HTTPException(422, "La duración mínima supera la duración del vídeo.")
        if not Path(video["source_path"]).is_file():
            raise HTTPException(404, "El archivo original ya no está disponible.")
        available = capabilities(settings)
        if not all(available["dependencies"].values()):
            raise HTTPException(503, "Instala Whisper local con scripts/setup-ai.ps1 antes de analizar.")
        model = next(m for m in available["models"] if m["id"] == body.model)
        if not model["installed"]:
            issue = model.get("integrity")
            if issue == "invalid":
                raise HTTPException(409, f"El modelo {body.model} tiene un SHA‑256 inválido. Vuelve a instalarlo en Momentos con IA.")
            if issue == "unreadable":
                raise HTTPException(409, f"El modelo {body.model} está bloqueado o no se puede leer.")
            raise HTTPException(409, f"El modelo {body.model} no está instalado. Instálalo en Momentos con IA.")
        try:
            with app.state.export_lock:
                return summary(app.state.analysis_queue.submit(find_video(identifier), body))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/videos/{identifier}/hook-titles")
    def hook_titles(identifier: str, start: float = 0, end: float | None = None):
        video = find_video(identifier)
        end = video["duration"] if end is None else end
        if not 0 <= start < end <= video["duration"] + .01:
            raise HTTPException(422, "El intervalo del clip no es válido.")
        titles = []
        for item in app.state.db.list("analyses"):
            if item["video_id"] != identifier or item["status"] != "completed":
                continue
            result = item["result"]
            moments = sorted(result["moments"], key=lambda moment: moment["score"], reverse=True)
            titles.extend(moment["title"] for moment in moments if moment["start"] < end and moment["end"] > start)
            words = [word["text"].strip() for word in result["transcript"]["words"]
                     if word["start"] < end and word["end"] > start]
            if words:
                titles.append(" ".join(words[:10])[:90])
        for candidate in app.state.db.list("autoclips"):
            if candidate.get("video_id") == identifier:
                titles.append(candidate["title"])
        return list(dict.fromkeys(title.strip() for title in titles if title.strip()))[:5]

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
        with app.state.export_lock:
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
            for layer in body.graphics:
                if layer.kind == "image" and layer.asset_id:
                    asset_file(app.state.db, settings, layer.asset_id)
            jobs = [enqueue_clip(c, {"analysis_id": analysis["id"], "moment_id": i, "score": lookup[i]["score"]})
                    for c, i in zip(clips, body.moment_ids)]
        return {"jobs": jobs, "count": len(jobs)}

    app.include_router(router)
