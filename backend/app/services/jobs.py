"""Cola local de un render a la vez; estado persistente y cancelación real."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
import subprocess
import tempfile
import time
import uuid

from ..database import Database, now
from .media import CREATE_NO_WINDOW


class JobQueue:
    def __init__(self, db: Database):
        self.db = db
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipzone-render")
        self.lock = Lock()
        self.processes: dict[str, subprocess.Popen] = {}
        self.closed = False
        for job in db.list("jobs"):
            if job["status"] in ("queued", "running"):
                job.update(status="failed", error="El proceso anterior se interrumpió. Vuelve a exportar.", updated_at=now())
                db.put("jobs", job)
                Path(job["output_path"]).unlink(missing_ok=True)
                if job["kind"] == "preview":
                    video = db.get("videos", job["video_id"])
                    if video:
                        video["preview_status"] = "failed"
                        db.put("videos", video)

    def submit(self, *, kind: str, video_id: str, command: list[str], output: Path, duration: float, title: str, settings: dict | None = None) -> dict:
        job = {"id": uuid.uuid4().hex, "kind": kind, "video_id": video_id, "title": title,
               "status": "queued", "progress": 0, "error": None, "created_at": now(), "updated_at": now(),
               "output_path": str(output), "settings": settings, "size": None}
        self.db.put("jobs", job)
        self.executor.submit(self._run, job["id"], command, output, duration)
        return job

    def _update(self, identifier: str, **changes):
        job = self.db.get("jobs", identifier)
        job.update(changes, updated_at=now())
        self.db.put("jobs", job)
        return job

    def _run(self, identifier: str, command: list[str], output: Path, duration: float):
        error = None
        try:
            with self.lock:
                job = self.db.get("jobs", identifier)
                if job["status"] == "cancelled" or self.closed:
                    return
                self._update(identifier, status="running")
                stderr_file = tempfile.TemporaryFile(mode="w+b")
                try:
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr_file,
                                               text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
                except Exception:
                    stderr_file.close()
                    raise
                self.processes[identifier] = process
            last_update = 0.0
            for line in process.stdout:
                if line.startswith("out_time_us=") and time.monotonic() - last_update > 0.4:
                    try:
                        progress = min(99, max(0, int(float(line.strip().split("=")[1]) / 1_000_000 / duration * 100)))
                    except ValueError:
                        continue
                    with self.lock:
                        if self.db.get("jobs", identifier)["status"] != "cancelled":
                            self._update(identifier, progress=progress)
                    last_update = time.monotonic()
            process.wait()
            stderr_file.seek(0)
            details = stderr_file.read().decode("utf-8", errors="replace")[-2000:]
            stderr_file.close()
            process.stdout.close()
            if process.returncode != 0:
                error = f"FFmpeg no pudo completar el vídeo: {details or 'proceso interrumpido'}"
        except Exception as exc:
            error = str(exc)
        finally:
            with self.lock:
                self.processes.pop(identifier, None)
                job = self.db.get("jobs", identifier)
                if job["status"] == "cancelled":
                    output.unlink(missing_ok=True)
                elif error:
                    self._update(identifier, status="failed", error=error)
                    output.unlink(missing_ok=True)
                else:
                    self._update(identifier, status="completed", progress=100, size=output.stat().st_size)
                if job["kind"] == "preview":
                    video = self.db.get("videos", job["video_id"])
                    video["preview_status"] = "ready" if self.db.get("jobs", identifier)["status"] == "completed" else "failed"
                    self.db.put("videos", video)

    def cancel(self, identifier: str):
        with self.lock:
            job = self.db.get("jobs", identifier)
            if job and job["status"] in ("queued", "running"):
                self._update(identifier, status="cancelled")
                if identifier in self.processes:
                    self.processes[identifier].terminate()
        return self.db.get("jobs", identifier)

    def shutdown(self):
        with self.lock:
            self.closed = True
            for job in self.db.list("jobs"):
                if job["status"] in ("queued", "running"):
                    self._update(job["id"], status="cancelled")
            for process in self.processes.values():
                process.terminate()
        self.executor.shutdown(wait=True, cancel_futures=True)
