"""Descarga explícita de un modelo oficial de Whisper con verificación SHA256."""
import argparse
import hashlib
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["tiny", "base", "small"], default="tiny")
    args = parser.parse_args()
    import whisper
    url = whisper._MODELS[args.model]
    expected = url.split("/")[-2]
    folder = Settings().model_dir
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{args.model}.pt"
    if target.is_file():
        with target.open("rb") as existing:
            valid = hashlib.file_digest(existing, "sha256").hexdigest() == expected
        if valid:
            print(f"Modelo verificado: {target}")
            return
    partial = target.with_suffix(".pt.part")
    checksum = hashlib.sha256()
    print(f"Descargando {args.model} desde el repositorio oficial de Whisper...", flush=True)
    try:
        with urlopen(url, timeout=60) as response, partial.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
                checksum.update(block)
        if checksum.hexdigest() != expected:
            raise RuntimeError("La comprobación SHA256 del modelo no coincide. Repite la descarga.")
        partial.replace(target)
        print(f"Modelo verificado y guardado: {target}")
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
