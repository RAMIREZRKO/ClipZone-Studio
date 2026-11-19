"""Subtitle translation through an optional, explicitly configured offline worker."""
import html
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys

from fastapi import HTTPException

from .config import ROOT

logger = logging.getLogger(__name__)
TIMING = re.compile(r"^(?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{3} --> (?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{3}(?:[ \t].*)?$")


def import_subtitle_text(content: str) -> list[str]:
    normalized = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    result = []
    for block in re.split(r"\n[ \t]*\n", normalized):
        lines = block.splitlines()
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        index = 0 if "-->" in lines[0] else 1
        if index >= len(lines) or not TIMING.fullmatch(lines[index].strip()):
            raise HTTPException(422, "El archivo contiene un bloque SRT/VTT sin un intervalo válido.")
        text = "\n".join(lines[index + 1:]).strip()
        result.append(html.unescape(re.sub(r"</?(?:i|b|u|c)(?:\.[\w-]+)?>", "", text, flags=re.IGNORECASE)))
    if not result:
        raise HTTPException(422, "No se encontraron subtítulos en el archivo SRT/VTT.")
    if any(len(text) > 600 for text in result):
        raise HTTPException(422, "Un segmento traducido supera los 600 caracteres.")
    return result


def argos_python() -> str | None:
    configured = os.getenv("CLIPZONE_ARGOS_PYTHON")
    if configured:
        candidate = Path(configured).expanduser()
        return str(candidate.resolve()) if candidate.is_file() else None
    return sys.executable if importlib.util.find_spec("argostranslate") else None


def translate_local(source: str, target: str, texts: list[str]) -> list[str]:
    executable = argos_python()
    if not executable:
        raise HTTPException(503, "Argos Translate no está configurado. Puedes editar o importar la traducción.")
    try:
        worker = subprocess.run(
            [executable, str(ROOT / "scripts" / "argos_worker.py")],
            input=json.dumps({"source": source, "target": target, "texts": texts}, ensure_ascii=False),
            capture_output=True, text=True, encoding="utf-8", timeout=150,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        result = json.loads(worker.stdout)
    except subprocess.TimeoutExpired as error:
        raise HTTPException(503, "La traducción local agotó el tiempo. Prueba con una página más corta.") from error
    except (ValueError, OSError) as error:
        logger.warning("No se pudo iniciar o leer la respuesta de Argos", exc_info=True)
        raise HTTPException(503, "No se pudo iniciar Argos Translate en el entorno configurado.") from error
    if worker.returncode or "error" in result:
        logger.warning("Argos devolvió un error (%s): %s", result.get("error"), worker.stderr[-1600:])
        if result.get("error") == "pair":
            raise HTTPException(422, f"Falta el paquete local directo {source} → {target}. Puedes importar o editar el texto.")
        raise HTTPException(503, "El motor local no pudo traducir. Comprueba Argos y los paquetes instalados.")
    translations = result.get("translations")
    if not isinstance(translations, list) or len(translations) != len(texts) or any(
        not isinstance(text, str) or len(text) > 600 for text in translations
    ):
        raise HTTPException(502, "Argos devolvió segmentos que no se pueden guardar.")
    return translations
