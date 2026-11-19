"""Worker JSON for an existing Argos environment and preinstalled direct language pair."""
from contextlib import redirect_stdout
import json
import os
import socket
import sys
import traceback


def offline(*args, **kwargs):
    raise OSError("ClipZone no permite conexiones desde el traductor local.")


def main():
    payload = json.load(sys.stdin)
    os.environ.update(
        ARGOS_MODEL_PROVIDER="OPENNMT", ARGOS_DEVICE_TYPE="cpu", ARGOS_CHUNK_TYPE="NONE",
        ARGOS_INTRA_THREADS="4", ARGOS_INTER_THREADS="1", ARGOS_BATCH_SIZE="8",
    )
    socket.create_connection = offline
    socket.getaddrinfo = offline
    socket.socket.connect = offline
    socket.socket.connect_ex = offline
    with redirect_stdout(sys.stderr):
        from argostranslate import package, translate

        source, target = payload["source"], payload["target"]
        direct = any(item.from_code == source and item.to_code == target for item in package.get_installed_packages())
        if not direct:
            return {"error": "pair"}
        languages = {language.code: language for language in translate.get_installed_languages()}
        engine = languages[source].get_translation(languages[target])
        return {"translations": [engine.translate(text) if text.strip() else "" for text in payload["texts"]]}


if __name__ == "__main__":
    try:
        print(json.dumps(main(), ensure_ascii=False))
    except Exception:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": "engine"}))
        raise SystemExit(1)
