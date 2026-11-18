"""Adaptador opcional: solo se carga cuando se invoca explícitamente.

Usa un modelo local previamente descargado. No descarga pesos en segundo plano.
La integración en la cola y el editor corresponde a la fase 2.
"""
from pathlib import Path
from .contracts import Word


class WhisperLocal:
    def __init__(self, model_path: Path, device: str = "cpu"):
        if not model_path.is_file():
            raise FileNotFoundError("Indica la ruta de un modelo Whisper local (.pt).")
        try:
            import whisper
        except ImportError as exc:
            raise RuntimeError("Instala backend/requirements-ai.txt para usar Whisper.") from exc
        self.model = whisper.load_model(str(model_path), device=device)

    def transcribe(self, source: Path, language: str | None = None) -> list[Word]:
        result = self.model.transcribe(str(source), language=language, word_timestamps=True, fp16=False)
        return [Word(text=w["word"].strip(), start=w["start"], end=w["end"])
                for segment in result["segments"] for w in segment.get("words", [])]
