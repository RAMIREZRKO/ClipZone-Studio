"""Borrado seguro por elemento, con diario recuperable en SQLite."""
from contextlib import contextmanager
import json
import logging
from pathlib import Path
import re
import sqlite3
import stat
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field
from ..ai.model_files import MODEL_HASHES

logger = logging.getLogger(__name__)
ACTIVE = {"queued", "running"}
ID = re.compile(r"[a-f0-9]{32}")
FOLDERS = ("uploads", "previews", "thumbnails", "exports", "analysis", "drafts", "quarantine", "graphics")


class RemoveRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
    remove_files: bool = False


class Storage:
    def __init__(self, db, data_dir, model_dir=None):
        self.db = db
        self.root = data_dir.resolve()
        self.model_dir = model_dir
        # Si el equipo se apagó a mitad de una operación, recupera antes que las colas.
        for entry in db.list("removals"):
            warning = self.finish(entry)
            if warning:
                logger.warning("Recuperación de archivos: %s", warning)

    def path(self, value, folder: str, name: str | None = None) -> Path:
        if folder not in FOLDERS:
            raise ValueError("Directorio administrado no reconocido.")
        candidate = Path(value).absolute()
        parent = self.root / folder
        if candidate.parent.resolve() != parent or not ID.fullmatch(candidate.stem):
            raise ValueError("La ruta está fuera del almacenamiento administrado.")
        expected = parent / candidate.name
        if candidate.resolve() != expected or (name is not None and candidate.name != name):
            raise ValueError("La ruta del archivo administrado no coincide con el registro.")
        if candidate.is_symlink() or (candidate.exists() and not stat.S_ISREG(candidate.stat().st_mode)):
            raise ValueError("Solo pueden eliminarse archivos administrados normales.")
        return expected

    def finish(self, entry: dict) -> str | None:
        pending = False
        for source, staged in entry["files"]:
            try:
                quarantine = self.path(staged, "quarantine")
                if entry["committed"]:
                    quarantine.unlink(missing_ok=True)
                elif quarantine.exists():
                    original = Path(source)
                    original = self.path(original, original.parent.name)
                    if original.exists():
                        pending = True
                        continue
                    quarantine.rename(original)
            except (OSError, ValueError):
                pending = True
        if pending:
            return "Hay archivos pendientes en cuarentena. Cierra los programas que los usan y reintenta la limpieza."
        try:
            with self.db.connect() as conn:
                conn.execute("DELETE FROM removals WHERE id=?", (entry["id"],))
        except sqlite3.Error:
            return "SQLite no pudo cerrar la operación. Reintenta la limpieza."
        return None

    def remove(self, records: dict[str, list[str]], files: list[Path]) -> str | None:
        for pending in self.db.list("removals"):
            affected = pending.get("records", {})
            if not pending["committed"] and any(set(ids).intersection(affected.get(table, [])) for table, ids in records.items()):
                raise ValueError("Hay archivos de este elemento pendientes de recuperar. Reintenta la limpieza antes de eliminarlo.")
        entry = {"id": uuid4().hex, "committed": False, "records": records,
                 "files": [(str(path), str(self.root / "quarantine" / f"{uuid4().hex}{path.suffix}"))
                           for path in dict.fromkeys(files) if path.exists()]}
        try:
            if entry["files"]:
                self.db.put("removals", entry)
            for original, staged in entry["files"]:
                self.path(staged, "quarantine")
                Path(original).rename(staged)
            with self.db.connect() as conn:
                for table, identifiers in records.items():
                    assert table in {"videos", "jobs", "analyses", "caption_tracks"}
                    conn.executemany(f"DELETE FROM {table} WHERE id=?", [(identifier,) for identifier in identifiers])
                if entry["files"]:
                    committed = {**entry, "committed": True}
                    conn.execute("UPDATE removals SET payload=? WHERE id=?", (json.dumps(committed), entry["id"]))
        except (OSError, ValueError, sqlite3.Error) as exc:
            warning = self.finish(entry)
            message = "No se pudo quitar este elemento. Comprueba si un archivo está bloqueado o la carpeta es de solo lectura."
            raise ValueError(f"{message} {warning or ''}".strip()) from exc
        if entry["files"]:
            return self.finish({**entry, "committed": True})
        return None

    def file_sizes(self, folder: str, partials: bool = False) -> int:
        directory = self.root / folder
        if directory.resolve() != directory:
            return 0
        total = 0
        for path in directory.iterdir():
            try:
                if (folder != "uploads" or (path.suffix == ".part") == partials) and not path.is_symlink() and path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
        return total

    def stats(self) -> dict:
        sizes = {folder: self.file_sizes(folder) for folder in FOLDERS}
        database_bytes = 0
        for name in ("clipzone.sqlite3", "clipzone.sqlite3-wal", "clipzone.sqlite3-shm"):
            try:
                database_bytes += (self.root / name).stat().st_size
            except OSError:
                pass
        transcripts_bytes = sum(
            len(json.dumps(a["result"]["transcript"], ensure_ascii=False).encode("utf-8"))
            for a in self.db.list("analyses") if a.get("result")
        )
        model_bytes = 0
        if self.model_dir:
            for model in MODEL_HASHES:
                try:
                    model_bytes += (self.model_dir / f"{model}.pt").stat().st_size
                except OSError:
                    pass
        partial_bytes = self.file_sizes("uploads", partials=True)
        return {
            "video_count": len(self.db.list("videos")),
            "export_count": sum(j["kind"] == "export" and j["status"] == "completed" for j in self.db.list("jobs")),
            "video_bytes": sizes["uploads"] + sizes["previews"] + sizes["thumbnails"],
            "export_bytes": sizes["exports"],
            "transcript_bytes": transcripts_bytes,
            "temporary_bytes": sizes["analysis"] + sizes["drafts"] + sizes["quarantine"] + partial_bytes,
            "database_bytes": database_bytes,
            "model_bytes": model_bytes,
            "graphics_bytes": sizes["graphics"],
            "total_bytes": sum(sizes.values()) + database_bytes + partial_bytes + model_bytes,
        }


def register_storage(app):
    router = APIRouter(prefix="/api", tags=["Almacenamiento"])

    @contextmanager
    def locked():
        state = app.state
        with state.export_lock, state.queue.lock, state.analysis_queue.lock:
            yield state.storage

    def active(item: dict, processes: dict) -> bool:
        return item["status"] in ACTIVE or item["id"] in processes

    def remove_item(storage: Storage, kind: str, identifier: str, physical: bool) -> dict:
        if not ID.fullmatch(identifier):
            raise ValueError("Identificador inválido.")
        table = "videos" if kind == "videos" else "jobs"
        db = storage.db
        item = db.get(table, identifier)
        if not item or (table == "jobs" and item["kind"] != "export"):
            return {"id": identifier, "status": "missing"}
        records = {table: [identifier]}
        files = []
        related = 0
        if table == "videos":
            jobs = [j for j in db.list("jobs") if j["video_id"] == identifier]
            analyses = [a for a in db.list("analyses") if a["video_id"] == identifier]
            if any(active(j, app.state.queue.processes) for j in jobs) or any(
                active(a, app.state.analysis_queue.processes) for a in analyses
            ):
                raise ValueError("El vídeo tiene procesos activos. Cancélalos o espera a que terminen.")
            related = sum(j["kind"] == "export" for j in jobs)
            records["jobs"] = [j["id"] for j in jobs if j["kind"] != "export"]
            records["analyses"] = [a["id"] for a in analyses]
            records["caption_tracks"] = [identifier]
            if physical:
                suffix = Path(item["source_path"]).suffix.lower()
                source = storage.path(item["source_path"], "uploads", identifier + suffix)
                files.append(source)
                if item["preview_path"] != item["source_path"]:
                    files.append(storage.path(item["preview_path"], "previews", f"{identifier}.mp4"))
                files.append(storage.path(item["thumbnail_path"], "thumbnails", f"{identifier}.jpg"))
                files.extend(storage.path(j["output_path"], "drafts") for j in jobs if j["kind"] == "draft")
        else:
            if active(item, app.state.queue.processes):
                raise ValueError("La exportación sigue en proceso. Cancélala o espera a que termine.")
            if physical:
                files.append(storage.path(item["output_path"], "exports"))
        warning = storage.remove(records, files)
        return {"id": identifier, "status": "removed", "related_exports": related, "warning": warning}

    def remove_batch(kind: str, body: RemoveRequest):
        results = []
        with locked() as storage:
            for identifier in dict.fromkeys(body.ids):
                try:
                    results.append(remove_item(storage, kind, identifier, body.remove_files))
                except (ValueError, OSError) as exc:
                    results.append({"id": identifier, "status": "blocked",
                                    "message": str(exc) if isinstance(exc, ValueError) else "No se pudo acceder a un archivo administrado."})
        return {"results": results}

    @router.post("/videos/remove")
    def remove_videos(body: RemoveRequest):
        return remove_batch("videos", body)

    @router.post("/exports/remove")
    def remove_exports(body: RemoveRequest):
        return remove_batch("exports", body)

    @router.get("/storage")
    def stats():
        return app.state.storage.stats()

    @router.post("/storage/cleanup")
    def clean():
        removed, errors = 0, []
        with locked() as storage:
            for entry in storage.db.list("removals"):
                warning = storage.finish(entry)
                if warning:
                    errors.append(warning)
            for job in storage.db.list("jobs"):
                if job["kind"] != "draft" or active(job, app.state.queue.processes):
                    continue
                try:
                    path = storage.path(job["output_path"], "drafts")
                    warning = storage.remove({"jobs": [job["id"]]}, [path])
                    if warning:
                        errors.append(warning)
                    removed += 1
                except (OSError, ValueError):
                    errors.append("No se pudo limpiar una vista exacta.")
            busy_analyses = {a["id"] for a in storage.db.list("analyses") if active(a, app.state.analysis_queue.processes)}
            known_drafts = {Path(j["output_path"]).stem for j in storage.db.list("jobs") if j["kind"] == "draft"}
            targets = [
                ("analysis", {".pcm", ".json"}, busy_analyses),
                ("drafts", {".mp4"}, known_drafts),
                ("uploads", {".part"}, app.state.active_uploads),
            ]
            for name, suffixes, busy in targets:
                folder = storage.root / name
                if folder.resolve() != folder:
                    continue
                for path in folder.iterdir():
                    if path.suffix not in suffixes or path.stem in busy or not ID.fullmatch(path.stem):
                        continue
                    try:
                        storage.path(path, name).unlink(missing_ok=True)
                        removed += 1
                    except (OSError, ValueError):
                        errors.append("No se pudo limpiar un archivo temporal.")
        return {"removed": removed, "errors": errors, "storage": storage.stats()}

    app.include_router(router)
