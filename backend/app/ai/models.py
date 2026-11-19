"""Disponibilidad local sin importar PyTorch en el proceso HTTP."""
import importlib.util
from ..config import Settings
from .model_files import inspect_model

MODEL_INFO = {"tiny": ("Tiny · rápido", 76), "base": ("Base · equilibrado", 145), "small": ("Small · más precisión", 484)}


def capabilities(settings: Settings) -> dict:
    dependencies = {name: importlib.util.find_spec(name) is not None for name in ("whisper", "torch", "numpy")}
    models = []
    for name, (label, size) in MODEL_INFO.items():
        status, _ = inspect_model(name, settings.model_dir)
        models.append({"id": name, "label": label, "size_mb": size, "installed": status == "verified", "integrity": status})
    return {"dependencies": dependencies, "models": models,
            "ready": all(dependencies.values()) and any(m["installed"] for m in models),
            "install_command": "powershell -ExecutionPolicy Bypass -File .\\scripts\\setup-ai.ps1 -DependenciesOnly"}
