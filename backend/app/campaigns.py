"""Local PNG assets and reusable, clip-independent campaign settings."""
from pathlib import Path
import struct
import subprocess
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .captions import Identifier
from .database import now
from .models import RenderOptions
from .services.media import CREATE_NO_WINDOW

MAX_PNG_BYTES = 16 * 1024 * 1024


class TemplateRequest(BaseModel):
    id: Identifier | None = None
    name: str = Field(min_length=1, max_length=80)
    options: RenderOptions


def example(channel: str, text: str, call: str) -> dict:
    return {
        "id": f"example-{channel.lower()}", "name": f"Campaña de {channel}", "example": True,
        "options": RenderOptions(
            captions={"enabled": True, "sidecars": False},
            graphics=[
                {"id": "1" * 32, "kind": "image", "name": f"Logo de {channel}", "x": 15, "y": 15, "size": 16},
                {"id": "2" * 32, "kind": "text", "name": "Nombre o enlace del canal", "text": text, "x": 50, "y": 16, "size": 43},
                {"id": "3" * 32, "kind": "text", "name": "Mensaje promocional", "text": call,
                 "x": 50, "y": 89, "size": 37, "color": "#b1f65a"},
            ],
        ).model_dump(mode="json"),
    }


EXAMPLES = [
    example("YouTube", "Nombre de tu canal", "Suscríbete para ver más"),
    example("Kick", "kick.com/tu-canal", "Sígueme en directo"),
]


def asset_file(db, settings, identifier: str) -> Path:
    if not db.get("assets", identifier):
        raise HTTPException(404, "El PNG de la capa ya no está disponible.")
    folder = settings.data_dir.resolve() / "graphics"
    filename = folder / f"{identifier}.png"
    if filename.resolve() != filename or not filename.is_file():
        raise HTTPException(404, "El PNG de la capa ya no está disponible.")
    return filename


def png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 33 or data[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise HTTPException(415, "Selecciona un archivo PNG válido.")
    width, height = struct.unpack(">II", data[16:24])
    if not (1 <= width <= 4096 and 1 <= height <= 4096):
        raise HTTPException(422, "El PNG debe medir como máximo 4096 × 4096.")
    return width, height


def register_campaigns(app, settings):
    router = APIRouter(prefix="/api", tags=["Gráficos y plantillas"])

    @router.post("/assets", status_code=201)
    def create_asset(file: UploadFile):
        try:
            data = file.file.read(MAX_PNG_BYTES + 1)
        finally:
            file.file.close()
        if len(data) > MAX_PNG_BYTES:
            raise HTTPException(413, "El PNG supera el límite de 16 MB.")
        width, height = png_dimensions(data)
        identifier = uuid4().hex
        root = settings.data_dir.resolve() / "graphics"
        if root.resolve() != root:
            raise HTTPException(409, "La carpeta de gráficos no es válida.")
        target = root / f"{identifier}.png"
        staged = root / f"{identifier}.part"
        try:
            staged.write_bytes(data)
            result = subprocess.run([app.state.media.require("ffmpeg"), "-nostdin", "-v", "error", "-xerror",
                                     "-threads", "2", "-f", "image2", "-pattern_type", "none", "-c:v", "png", "-i", str(staged),
                                     "-frames:v", "1", "-f", "null", "-"], capture_output=True,
                                    timeout=12, creationflags=CREATE_NO_WINDOW)
            if result.returncode:
                raise HTTPException(422, "El contenido del PNG está incompleto o dañado.")
            name = (file.filename or "Logo.png").replace("\\", "/").rsplit("/", 1)[-1][:120]
            metadata = {"id": identifier, "name": name, "width": width, "height": height,
                        "url": f"/api/assets/{identifier}", "size": len(data)}
            staged.replace(target)
            try:
                return app.state.db.put("assets", metadata)
            except Exception:
                target.unlink(missing_ok=True)
                raise
        except subprocess.TimeoutExpired as error:
            raise HTTPException(422, "FFmpeg no pudo leer el PNG a tiempo.") from error
        finally:
            staged.unlink(missing_ok=True)

    @router.get("/assets/{identifier}")
    def get_asset(identifier: Identifier):
        return FileResponse(asset_file(app.state.db, settings, identifier), media_type="image/png")

    @router.get("/templates")
    def list_templates():
        return EXAMPLES + app.state.db.list("templates")

    @router.post("/templates")
    def save_template(body: TemplateRequest):
        name = body.name.strip()
        if not name:
            raise HTTPException(422, "La plantilla necesita un nombre.")
        options = body.options.model_dump(mode="json")
        if options["captions"]:
            options["captions"]["revision"] = None
        with app.state.export_lock:
            if body.id and not app.state.db.get("templates", body.id):
                raise HTTPException(404, "La plantilla guardada ya no está disponible.")
            for layer in body.options.graphics:
                if layer.kind == "image" and layer.asset_id:
                    asset_file(app.state.db, settings, layer.asset_id)
            return app.state.db.put("templates", {"id": body.id or uuid4().hex, "name": name, "example": False,
                                                   "options": options, "updated_at": now()})

    app.include_router(router)
