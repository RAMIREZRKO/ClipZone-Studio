"""Inicia el servidor y abre el navegador solo cuando responde."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import APP_VERSION, Settings, instance_identity
from app.storage_location import LibraryInUse

HOST, PORT = "127.0.0.1", 8000
URL = f"http://{HOST}:{PORT}"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_json(endpoint: str) -> dict | None:
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(URL + endpoint, timeout=.8) as response:
            data = json.loads(response.read(8192))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def port_occupied() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=.4):
            return True
    except OSError:
        return False


def matches(instance: dict | None, settings: Settings) -> bool:
    expected = instance_identity(Path(settings.location.read()["directory"]))
    return instance is not None and all(instance.get(key) == value for key, value in expected.items())


def open_browser() -> bool:
    if os.name == "nt":
        try:
            os.startfile(URL)
            return True
        except OSError:
            pass
    try:
        return webbrowser.open(URL, new=2)
    except (OSError, webbrowser.Error):
        return False


def open_interface() -> int:
    if open_browser():
        return 0
    print(f"Windows no abrió el navegador. Puedes entrar en {URL}.", file=sys.stderr)
    return 5


def wait_for_instance(settings: Settings, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if matches(local_json("/api/instance"), settings):
            return True
        time.sleep(.25)
    return False


def open_when_ready(settings: Settings) -> None:
    if wait_for_instance(settings, 45):
        open_interface()
    else:
        print(f"ClipZone tardó en responder. Cuando termine de iniciar, abre {URL}.", file=sys.stderr)


def reuse_server(should_open: bool) -> int:
    if should_open:
        print(f"ClipZone Studio ya está en ejecución. Abriendo {URL}.", flush=True)
        return open_interface()
    print(f"ClipZone Studio ya está en ejecución en {URL}.", file=sys.stderr)
    return 3


def report_port_conflict(current: dict | None) -> int:
    legacy = local_json("/api/health") if current is None else None
    old_version = (current or legacy or {}).get("version")
    clipzone = (current or {}).get("app") == "clipzone-studio" or "max_upload_bytes" in (legacy or {})
    if clipzone and old_version and old_version != APP_VERSION:
        print(f"El puerto {PORT} sigue usando ClipZone Studio {str(old_version)[:30]}. "
              "Guarda los búferes y cierra ese servidor antes de iniciar la versión actual.", file=sys.stderr)
    else:
        print(f"El puerto {PORT} está ocupado por otro servidor o por ClipZone con otra biblioteca.", file=sys.stderr)
    return 3


def main() -> int:
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    current = local_json("/api/instance")
    if matches(current, settings):
        return reuse_server(args.open)
    try:
        with settings.location.guard():
            pass
    except LibraryInUse as exc:
        if args.open and wait_for_instance(settings, 8):
            return reuse_server(args.open)
        print(exc, file=sys.stderr)
        if port_occupied():
            return report_port_conflict(current)
        return 3
    if port_occupied():
        if args.open and current is None and wait_for_instance(settings, 3):
            return reuse_server(args.open)
        return report_port_conflict(current)
    if args.check:
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "doctor.py")], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
        if not args.dev and not (settings.frontend_dir / "index.html").is_file():
            print("Compila el editor desde frontend con npm ci y npm run build.", file=sys.stderr)
            return 1
    print(f"ClipZone Studio: {URL} | Ctrl+C para cerrar.", flush=True)
    if args.dev:
        print("Modo desarrollo. Ejecuta npm run dev desde frontend para usar el puerto 5173.", flush=True)
    if args.open:
        threading.Thread(target=open_when_ready, args=(settings,), daemon=True).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=args.dev,
                reload_dirs=[str(ROOT / "backend" / "app")] if args.dev else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
