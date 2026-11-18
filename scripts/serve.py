"""Inicia el servidor y abre el navegador solo cuando responde."""
import argparse
from pathlib import Path
import sys
import threading
import time
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def open_when_ready():
    for _ in range(60):
        try:
            with urlopen("http://127.0.0.1:8000/api/health", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open("http://127.0.0.1:8000")
                    return
        except OSError:
            pass
        time.sleep(.3)


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    if args.open:
        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=args.dev,
                reload_dirs=[str(ROOT / "backend" / "app")] if args.dev else None)
