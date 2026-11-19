"""Instala explícitamente un modelo oficial utilizando el mismo verificador que la interfaz."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai.model_files import (
    MODEL_HASHES, DownloadError, close_diagnostic_logger, create_diagnostic_logger, download_model, inspect_model,
)
from app.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=MODEL_HASHES, default="base")
    parser.add_argument("--verify", action="store_true", help="Verifica todos los modelos locales sin descargarlos.")
    args = parser.parse_args()
    settings = Settings()
    if args.verify:
        failed = False
        print(f"Carpeta de modelos: {settings.model_dir.resolve()}")
        for model in MODEL_HASHES:
            status, digest = inspect_model(model, settings.model_dir)
            label = {"verified": "verificado", "invalid": "SHA-256 inválido", "unreadable": "no se puede leer", "missing": "ausente"}[status]
            print(f"{model}: {label}" + (f" | SHA-256 {digest}" if digest else ""))
            failed |= status in {"invalid", "unreadable"}
        if failed:
            raise SystemExit(1)
        return
    log_file = settings.data_dir / "whisper-downloads.log"
    diagnostics = create_diagnostic_logger(log_file)
    print(f"Comprobando o descargando el modelo {args.model}...", flush=True)
    try:
        target = download_model(args.model, settings.model_dir, diagnostics=diagnostics)
    except DownloadError as exc:
        diagnostics.error("Fallo model=%s code=%s", args.model, exc.code, exc_info=True)
        raise SystemExit(f"{exc} Registro: {log_file}") from None
    finally:
        close_diagnostic_logger(diagnostics)
    print(f"Modelo verificado: {target}")


if __name__ == "__main__":
    main()
