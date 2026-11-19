"""Diagnóstico sin modificar el equipo. Ejecutar con .venv/Scripts/python.exe."""
import importlib.util
import subprocess
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings
from app.ai.models import capabilities
from app.translation import argos_python


def main() -> int:
    settings = Settings()
    okay = True
    print(f"Python {sys.version.split()[0]} | {sys.executable}")
    for name in ("fastapi", "uvicorn", "pydantic", "multipart"):
        found = importlib.util.find_spec(name) is not None
        print(f"[{'OK' if found else 'FALTA'}] {name}")
        okay &= found
    for name in ("ffmpeg", "ffprobe"):
        binary = settings.binary(name)
        if binary:
            result = subprocess.run([binary, "-version"], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            print(f"[{'OK' if result.returncode == 0 else 'ERROR'}] {result.stdout.splitlines()[0] if result.stdout else name}")
            okay &= result.returncode == 0
            if name == "ffmpeg":
                encoders = subprocess.run([binary, "-hide_banner", "-encoders"], capture_output=True, text=True,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
                supported = "libx264" in encoders and " aac " in encoders
                print(f"[{'OK' if supported else 'FALTA'}] Codificadores libx264 y AAC")
                okay &= supported
                filters = subprocess.run([binary, "-hide_banner", "-filters"], capture_output=True, text=True,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
                ass_available = bool(re.search(r"\bass\s+V->V", filters))
                print(f"[{'OK' if ass_available else 'FALTA'}] libass para subtitulos incrustados")
        else:
            print(f"[FALTA] {name}. Agregalo al PATH o ejecuta scripts/setup.ps1 -DownloadFFmpeg.")
            okay = False
    print(f"[INFO] Datos locales: {settings.data_dir}")
    print(f"[INFO] Frontend compilado: {'si' if (settings.frontend_dir / 'index.html').is_file() else 'no'}")
    ai = capabilities(settings)
    print(f"[INFO] IA local: {'lista' if ai['ready'] else 'ejecuta scripts/setup-ai.ps1 para activarla'}")
    for model in ai['models']:
        print(f"[INFO] Whisper {model['id']}: {'instalado' if model['installed'] else 'sin instalar'} (~{model['size_mb']} MB)")
    print(f"[INFO] Argos opcional: {'entorno configurado' if argos_python() else 'edicion e importacion manual disponibles'}")
    return 0 if okay else 1


if __name__ == "__main__":
    raise SystemExit(main())
