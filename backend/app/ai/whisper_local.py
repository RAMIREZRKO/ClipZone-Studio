"""Adaptador Whisper local, cargado exclusivamente en el worker de análisis."""
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

    def transcribe_result(self, source, language: str | None = None) -> dict:
        return self.model.transcribe(str(source) if isinstance(source, Path) else source, language=language,
                                     word_timestamps=True, fp16=False, verbose=None, temperature=0,
                                     condition_on_previous_text=False)

    def transcribe(self, source, language: str | None = None) -> list[Word]:
        result = self.transcribe_result(source, language)
        return [Word(text=w["word"].strip(), start=w["start"], end=w["end"])
                for segment in result["segments"] for w in segment.get("words", [])]
