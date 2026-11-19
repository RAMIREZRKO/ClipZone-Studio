"""Subproceso cancelable. Lee PCM por bloques: no carga un vídeo largo en RAM."""
import argparse
import json
from pathlib import Path
import sys


def emit(progress: int, stage: str):
    print(json.dumps({"progress": progress, "stage": stage}), flush=True)


def run(audio: Path, model: Path, language: str, output: Path):
    import numpy as np
    import torch
    from .whisper_local import WhisperLocal
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    emit(20, "Cargando modelo Whisper")
    engine = WhisperLocal(model)
    duration = audio.stat().st_size / 32000
    words = []
    energies = []
    detected_language = None if language == "auto" else language
    with audio.open("rb") as stream:
        offset = 0.0
        while block := stream.read(60 * 32000):
            samples = np.frombuffer(block, dtype="<i2").astype(np.float32) / 32768
            for i in range(0, len(samples), 16000):
                energies.append(round(float(np.sqrt(np.mean(samples[i:i + 16000] ** 2))), 5))
            # Omite bloques sin señal para reducir alucinaciones en silencio digital.
            if float(np.sqrt(np.mean(samples ** 2))) > .0003:
                result = engine.transcribe_result(samples, detected_language)
                detected_language = result.get("language") or detected_language
                for segment in result.get("segments", []):
                    if segment.get("no_speech_prob", 0) > .6 and segment.get("avg_logprob", 0) < -1:
                        continue
                    for word in segment.get("words", []):
                        start, end = max(0, float(word["start"]) + offset), min(duration, float(word["end"]) + offset)
                        if end > start and str(word["word"]).strip():
                            words.append({"text": word["word"].strip(), "start": round(start, 3), "end": round(end, 3)})
            offset += len(samples) / 16000
            emit(min(92, 25 + int(offset / max(duration, .01) * 67)), "Transcribiendo audio")
    output.write_text(json.dumps({"words": words, "language": detected_language or language,
                                  "text": " ".join(w["text"] for w in words), "energy": energies}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.audio, args.model, args.language, args.output)
    except Exception as exc:
        print(f"No se pudo transcribir con Whisper: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
