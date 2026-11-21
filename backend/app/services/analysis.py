"""Cola independiente para Whisper; conserva transcripciones y permite reutilizarlas."""
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from threading import Condition, RLock
import json
import os
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from ..ai.contracts import Word
from ..ai.detector import detect_moments
from ..config import ROOT, Settings
from ..database import Database, now
from ..models import AnalysisRequest
from .media import CREATE_NO_WINDOW
from .direct_source import terminate_tree


class AnalysisCancelled(Exception):
    pass


class LiveWhisperQueueTimeout(TimeoutError):
    pass


class LiveWhisperError(RuntimeError):
    pass


class AnalysisQueue:
    def __init__(self, db: Database, settings: Settings):
        self.db, self.settings = db, settings
        self.lock = RLock()
        self.whisper_queue = Condition()
        self.whisper_turns = deque()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipzone-ai")
        self.processes: dict[str, subprocess.Popen] = {}
        self.closed = False
        for item in db.list("analyses"):
            if item["status"] in {"queued", "running"}:
                item.update(status="failed", stage="Interrumpido", error="El análisis anterior se interrumpió. Puedes repetirlo.", updated_at=now())
                db.put("analyses", item)
                self._cleanup(item["id"])

    def _paths(self, identifier: str):
        folder = self.settings.data_dir / "analysis"
        return folder / f"{identifier}.pcm", folder / f"{identifier}.json"

    def _cleanup(self, identifier: str):
        for path in self._paths(identifier):
            path.unlink(missing_ok=True)

    def _update(self, identifier: str, **changes):
        with self.lock:
            item = self.db.get("analyses", identifier)
            if not item or item["status"] == "cancelled":
                raise AnalysisCancelled()
            item.update(changes, updated_at=now())
            return self.db.put("analyses", item)

    def submit(self, video: dict, options: AnalysisRequest) -> dict:
        with self.lock:
            pending = [a for a in self.db.list("analyses") if a["status"] in {"queued", "running"}]
            if any(a["video_id"] == video["id"] for a in pending):
                raise ValueError("Ya hay un análisis en curso para este vídeo.")
            if len(pending) >= 3:
                raise ValueError("Hay tres análisis pendientes. Espera a que termine alguno.")
            item = {"id": uuid4().hex, "video_id": video["id"], "status": "queued", "stage": "En cola",
                    "progress": 0, "error": None, "created_at": now(), "updated_at": now(),
                    "options": options.model_dump(), "result": None, "reused_transcript": False}
            self.db.put("analyses", item)
            self.executor.submit(self._run, item["id"], video, options)
            return item

    def _check(self, identifier: str):
        item = self.db.get("analyses", identifier)
        if self.closed or not item or item["status"] == "cancelled":
            raise AnalysisCancelled()

    def _worker_command(self, audio: Path, model: Path, language: str, result: Path) -> list[str]:
        return [sys.executable, "-m", "app.ai.worker", "--audio", str(audio), "--model", str(model),
                "--language", language, "--output", str(result)]

    @contextmanager
    def whisper_turn(self, check):
        ticket = object()
        with self.whisper_queue:
            self.whisper_turns.append(ticket)
        try:
            with self.whisper_queue:
                while self.whisper_turns[0] is not ticket:
                    check()
                    self.whisper_queue.wait(.2)
            check()
            yield
        finally:
            with self.whisper_queue:
                self.whisper_turns.remove(ticket)
                self.whisper_queue.notify_all()

    def _process(self, identifier: str, command: list[str], *, whisper: bool, duration: float, cpu_threads: int = 4):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "PYTHONUTF8": "1"}
        if whisper:
            env.update(CLIPZONE_WHISPER_THREADS=str(cpu_threads), OMP_NUM_THREADS=str(cpu_threads))
        with tempfile.TemporaryFile(mode="w+b") as errors:
            with self.lock:
                self._check(identifier)
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True,
                                           encoding="utf-8", errors="replace", env=env, creationflags=CREATE_NO_WINDOW)
                self.processes[identifier] = process
            try:
                for line in process.stdout:
                    with self.lock:
                        self._check(identifier)
                        if whisper:
                            try:
                                event = json.loads(line)
                                self._update(identifier, progress=min(92, int(event["progress"])), stage=str(event["stage"]))
                            except (ValueError, KeyError, TypeError):
                                pass
                        elif line.startswith("out_time_us="):
                            try:
                                progress = min(18, int(float(line.split("=")[1]) / 1_000_000 / max(duration, .01) * 18))
                                self._update(identifier, progress=max(1, progress))
                            except ValueError:
                                pass
                process.wait()
                self._check(identifier)
                if process.returncode:
                    errors.seek(0)
                    detail = errors.read().decode("utf-8", errors="replace")[-1800:]
                    raise RuntimeError(detail or "El proceso de análisis terminó con error.")
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait()
                process.stdout.close()
                with self.lock:
                    self.processes.pop(identifier, None)

    def _run(self, identifier: str, video: dict, options: AnalysisRequest):
        audio, output = self._paths(identifier)
        started = time.monotonic()
        try:
            with self.lock:
                self._check(identifier)
                self._update(identifier, status="running", stage="Preparando audio")
            cached = next((a for a in self.db.list("analyses") if a["video_id"] == video["id"] and a["status"] == "completed"
                           and a.get("options", {}).get("model") == options.model
                           and a.get("options", {}).get("language") == options.language
                           and not a.get("options", {}).get("transcript_window") and a.get("result")), None)
            window = options.transcript_window
            duration = window[1] - window[0] if window else video["duration"]
            if options.reuse_transcript and not window and cached:
                transcript = cached["result"]["transcript"]
                self._update(identifier, progress=92, stage="Reutilizando transcripción", reused_transcript=True)
            else:
                ffmpeg = self.settings.binary("ffmpeg")
                if not ffmpeg:
                    raise RuntimeError("Falta FFmpeg para extraer el audio.")
                command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe",
                           *(["-ss", str(window[0])] if window else []), "-i", video["source_path"],
                           *(["-t", str(duration)] if window else []), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                           "-f", "s16le", "-progress", "pipe:1", "-nostats", str(audio)]
                self._process(identifier, command, whisper=False, duration=duration)
                self._update(identifier, stage="En cola de Whisper")
                with self.whisper_turn(lambda: self._check(identifier)):
                    self._process(identifier, self._worker_command(audio, self.settings.model_dir / f"{options.model}.pt", options.language, output),
                                  whisper=True, duration=duration, cpu_threads=options.cpu_threads)
                transcript = json.loads(output.read_text(encoding="utf-8"))
                if window:
                    for word in transcript["words"]:
                        word["start"] = min(window[1], word["start"] + window[0])
                        word["end"] = min(window[1], word["end"] + window[0])
                    transcript["words"] = [word for word in transcript["words"] if word["end"] > word["start"]]
                    transcript["text"] = " ".join(word["text"] for word in transcript["words"])
            self._check(identifier)
            self._update(identifier, progress=95, stage="Detectando y puntuando momentos")
            words = [Word(**w) for w in transcript["words"]]
            moments = [] if window else detect_moments(words, video["duration"], options.min_duration, options.max_duration,
                                     options.max_clips, transcript.get("energy"))
            with self.lock:
                self._check(identifier)
                self._update(identifier, status="completed", progress=100, stage="Análisis listo",
                             elapsed_seconds=round(time.monotonic() - started, 2),
                             result={"transcript": transcript, "moments": moments, "scoring_version": "local-v1"})
        except AnalysisCancelled:
            pass
        except Exception as exc:
            with self.lock:
                item = self.db.get("analyses", identifier)
                if item and item["status"] != "cancelled":
                    self._update(identifier, status="failed", stage="No se pudo analizar", error=str(exc)[-2000:])
        finally:
            self._cleanup(identifier)

    def transcribe_live(self, audio: Path, model: str, output: Path, stop, on_start=None) -> dict | None:
        expires = time.monotonic() + 60
        def check():
            if self.closed or stop.is_set():
                raise AnalysisCancelled()
            if time.monotonic() >= expires:
                raise LiveWhisperQueueTimeout("Se agotaron los 60 s de espera en la cola de Whisper.")
        try:
            with self.whisper_turn(check):
                if on_start:
                    on_start()
                return self._transcribe_candidate(audio, model, output, stop)
        except AnalysisCancelled:
            return None

    def _transcribe_candidate(self, audio: Path, model: str, output: Path, stop) -> dict | None:
        env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "PYTHONUTF8": "1",
               "CLIPZONE_WHISPER_THREADS": "2", "OMP_NUM_THREADS": "2"}
        command = [*self._worker_command(audio, self.settings.model_dir / f"{model}.pt", "auto", output),
                   "--live-evidence"]
        deadline = time.monotonic() + 50
        with tempfile.TemporaryFile(mode="w+b") as errors, subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
            env=env, creationflags=CREATE_NO_WINDOW, start_new_session=os.name != "nt",
        ) as process:
            try:
                while process.poll() is None:
                    if stop.wait(.2) or self.closed:
                        return None
                    if time.monotonic() > deadline:
                        raise LiveWhisperError(f"Whisper {model} superó los 50 s de inferencia del candidato.")
                if process.returncode:
                    errors.seek(0, os.SEEK_END)
                    errors.seek(max(0, errors.tell() - 1500))
                    details = errors.read().decode("utf-8", errors="replace").strip()
                    raise LiveWhisperError(f"Whisper {model} no pudo transcribir el candidato. {details}".strip())
                return json.loads(output.read_text(encoding="utf-8"))
            finally:
                terminate_tree(process)

    def cancel(self, identifier: str):
        with self.lock:
            item = self.db.get("analyses", identifier)
            if item and item["status"] in {"queued", "running"}:
                self._update(identifier, status="cancelled", stage="Cancelado")
                process = self.processes.get(identifier)
                if process and process.poll() is None:
                    process.terminate()
            return self.db.get("analyses", identifier)

    def shutdown(self):
        with self.lock:
            for item in self.db.list("analyses"):
                self.cancel(item["id"])
            self.closed = True
        self.executor.shutdown(wait=True, cancel_futures=True)
