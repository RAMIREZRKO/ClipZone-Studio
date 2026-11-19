"""Disponibilidad local sin importar PyTorch en el proceso HTTP."""
import importlib.util
from ..config import Settings

MODEL_INFO = {"tiny": ("Tiny · rápido", 76), "base": ("Base · equilibrado", 145), "small": ("Small · más precisión", 484)}


def capabilities(settings: Settings) -> dict:
    dependencies = {name: importlib.util.find_spec(name) is not None for name in ("whisper", "torch", "numpy")}
    models = [{"id": name, "label": label, "size_mb": size, "installed": (settings.model_dir / f"{name}.pt").is_file()}
              for name, (label, size) in MODEL_INFO.items()]
    return {"dependencies": dependencies, "models": models,
            "ready": all(dependencies.values()) and any(m["installed"] for m in models),
            "install_command": "powershell -ExecutionPolicy Bypass -File .\\scripts\\setup-ai.ps1 -Model tiny"}
