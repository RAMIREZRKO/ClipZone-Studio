"""Ubicación persistente y migración verificada antes de iniciar los servicios."""
from contextlib import closing, contextmanager
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import stat
from tempfile import NamedTemporaryFile, TemporaryDirectory

from .database import TABLES

logger = logging.getLogger(__name__)
GB = 10**9
DISK_WARN = 10 * GB
CAPTURE_STOP = 5 * GB
DRAFT_LIMIT = GB
DATABASE = "clipzone.sqlite3"
SIDECARS = (DATABASE + "-wal", DATABASE + "-shm", DATABASE + "-journal")


class LocationError(ValueError):
    pass


class LibraryInUse(LocationError):
    pass


def local_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.drive.startswith("\\\\") or path.resolve() != path:
        raise LocationError("Selecciona una ruta absoluta en un disco local, sin enlaces ni uniones de Windows.")
    return path


def reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def browse_folders(directory: str | None) -> dict:
    if directory is None and os.name == "nt":
        from ctypes import windll
        mask = windll.kernel32.GetLogicalDrives()
        drives = [f"{chr(65 + bit)}:\\" for bit in range(26) if mask & (1 << bit)]
        return {"path": None, "parent": None,
                "folders": [drive for drive in drives if windll.kernel32.GetDriveTypeW(drive) in (2, 3)]}
    folder = local_path(directory or "/")
    entries = []
    for entry in folder.iterdir():
        try:
            info = entry.lstat()
            if stat.S_ISDIR(info.st_mode) and not reparse(info):
                entries.append(str(entry))
        except OSError:
            continue
    parent = None if folder == folder.parent else str(folder.parent)
    return {"path": str(folder), "parent": parent, "folders": sorted(entries, key=str.casefold)[:250]}


def digest(path: Path) -> str:
    checksum = sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024**2):
            checksum.update(block)
    return checksum.hexdigest()


def inventory(root: Path) -> tuple[list[Path], dict[Path, os.stat_result]]:
    def inaccessible(error):
        raise error

    folders, files = [], {}
    for folder, dirs, names in os.walk(root, onerror=inaccessible):
        folder = Path(folder)
        folders.append(folder.relative_to(root))
        for name in [*dirs, *names]:
            path = folder / name
            info = path.lstat()
            if reparse(info) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise LocationError(f"No se puede migrar un enlace o archivo especial: {path}.")
            if stat.S_ISREG(info.st_mode):
                files[path.relative_to(root)] = info
    return folders, files


def remap_paths(conn: sqlite3.Connection, source: Path, destination: Path) -> None:
    def change(value):
        if not isinstance(value, str):
            return value
        path = Path(value).absolute()
        if path.is_relative_to(source):
            return str(destination / path.relative_to(source))
        return value

    paths = {"videos": ("source_path", "preview_path", "thumbnail_path"), "jobs": ("output_path",)}
    tables = {name for name, in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in (set(paths) | {"removals"}) & tables:
        for identifier, raw in conn.execute(f"SELECT id, payload FROM {table}"):
            row = json.loads(raw)
            if table == "removals":
                row["files"] = [[change(a), change(b)] for a, b in row["files"]]
            else:
                for field in paths[table]:
                    if field in row:
                        row[field] = change(row[field])
            conn.execute(f"UPDATE {table} SET payload=? WHERE id=?", (json.dumps(row), identifier))


def check_db(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise LocationError("SQLite no superó la comprobación de integridad.")


def copy_database(source: Path, stage: Path, destination: Path) -> None:
    # SQLite copia la vista confirmada completa, incluso si hay páginas en WAL.
    with closing(sqlite3.connect(source / DATABASE)) as old, closing(sqlite3.connect(stage / DATABASE)) as new:
        check_db(old)
        old.backup(new)
        for table in TABLES | {"live_captures"}:
            query = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?"
            if old.execute(query, (table,)).fetchone():
                rows = f"SELECT id, payload FROM {table} ORDER BY id"
                if old.execute(rows).fetchall() != new.execute(rows).fetchall():
                    raise LocationError(f"La copia de SQLite no coincide en {table}.")
        with new:
            remap_paths(new, source, destination)
        check_db(new)
        # Publica un archivo completo sin depender de archivos .wal o .shm del área de copiado.
        new.execute("PRAGMA journal_mode=DELETE")


class StorageLocation:
    def __init__(self, default: Path, config: Path | None):
        self.default = default.absolute()
        self.config = config.absolute() if config else None

    def read(self) -> dict:
        if not self.config or not self.config.exists():
            return {"directory": str(self.default)}
        return json.loads(self.config.read_text(encoding="utf-8"))

    def write(self, settings: dict) -> None:
        if not self.config:
            raise LocationError("La ubicación está fijada por CLIPZONE_DATA_DIR.")
        self.config.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=self.config.parent, delete=False, suffix=".tmp") as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(settings, ensure_ascii=False).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            temporary.replace(self.config)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def guard(self):
        # Una sola instancia puede usar o migrar una misma configuración de biblioteca.
        if not self.config:
            yield
            return
        self.config.parent.mkdir(parents=True, exist_ok=True)
        with self.config.with_suffix(".lock").open("a+b") as handle:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                library = self.read()["directory"]
                raise LibraryInUse(
                    f"Otra instancia de ClipZone Studio ya está usando la biblioteca «{library}». "
                    "Puedes seguir usando la instancia abierta. Para reiniciarla, detén su servidor con Ctrl+C "
                    "y vuelve a iniciar ClipZone Studio."
                ) from exc
            yield

    def target(self, directory: str, source: Path) -> Path:
        destination = local_path(directory)
        if (destination == Path(destination.anchor) or destination.is_relative_to(source)
                or source.is_relative_to(destination) or (self.config and self.config.is_relative_to(destination))):
            raise LocationError("La carpeta nueva debe estar separada de la biblioteca y de la configuración de ClipZone.")
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise LocationError("Elige una carpeta vacía o una que todavía no exista.")
        return destination

    def schedule(self, directory: str | None) -> dict:
        current = self.read()
        if directory is None:
            return self.clear()
        source = local_path(current["directory"])
        destination = self.target(directory, source)
        self.write({"directory": str(source), "pending": str(destination)})
        return self.read()

    def clear(self) -> dict:
        current = {"directory": self.read()["directory"]}
        self.write(current)
        return current

    def startup(self, check_captures) -> Path:
        current = self.read()
        source = local_path(current["directory"])
        if not current.get("pending"):
            return source
        try:
            check_captures()
            return self.migrate(source, self.target(current["pending"], source))
        except (OSError, ValueError, sqlite3.Error) as exc:
            logger.exception("No se pudo migrar el almacenamiento.")
            self.write({**current, "error": str(exc)})
            return source

    def migrate(self, source: Path, destination: Path) -> Path:
        if not (source / DATABASE).is_file():
            raise LocationError("No se encontró la base de datos de la biblioteca de origen.")
        folders, files = inventory(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(destination.parent).free < sum(info.st_size for info in files.values()) + CAPTURE_STOP:
            raise LocationError("La unidad de destino no tiene espacio para copiar los datos y conservar 5 GB libres.")

        copied = {}
        with TemporaryDirectory(dir=destination.parent, prefix=".clipzone-copy-") as directory:
            stage = Path(directory)
            for folder in folders:
                (stage / folder).mkdir(exist_ok=True)
            for name, info in files.items():
                if name.parent == Path(".") and name.name in (DATABASE, *SIDECARS):
                    continue
                original, target = source / name, stage / name
                if original.resolve() != original:
                    raise LocationError(f"La ruta de origen cambió durante la migración: {original}.")
                shutil.copy2(original, target)
                expected = digest(original)
                if target.stat().st_size != info.st_size or digest(target) != expected:
                    raise LocationError(f"Falló la verificación SHA-256 de {name}. Se conserva el origen.")
                copied[name] = expected
            copy_database(source, stage, destination)
            old_database = {name: digest(source / name) for name in (DATABASE, DATABASE + "-wal")
                            if (source / name).is_file()}
            new_database = digest(stage / DATABASE)
            # No reemplaces una carpeta si otro proceso la ocupó durante la copia.
            self.target(str(destination), source)
            if destination.exists():
                destination.rmdir()
            stage.rename(destination)
        self.write({"directory": str(destination), "previous": str(source), "verified_files": len(copied)})
        try:
            self.remove_verified(source, destination, folders, copied, old_database, new_database)
        except (OSError, ValueError, sqlite3.Error) as exc:
            logger.exception("La biblioteca nueva está lista, pero quedaron copias antiguas.")
            self.write({**self.read(), "warning": f"Quedaron copias antiguas en {source}: {exc}"})
        return destination

    @staticmethod
    def remove_verified(source: Path, destination: Path, folders: list[Path], copied: dict[Path, str],
                        old_database: dict[str, str], new_database: str) -> None:
        for name, expected in copied.items():
            original, target = source / name, destination / name
            if (original.resolve() != original or target.resolve() != target or
                    digest(original) != expected or digest(target) != expected):
                raise LocationError(f"El archivo {name} cambió. Se conservan las copias de origen.")
        if (digest(destination / DATABASE) != new_database
                or any((source / name).is_file() != (name in old_database)
                       for name in (DATABASE, DATABASE + "-wal"))
                or any(digest(source / name) != expected for name, expected in old_database.items())):
            raise LocationError("SQLite cambió después de verificar la copia. Se conserva el origen.")
        for name in copied:
            (source / name).unlink()
        for name in (*SIDECARS, DATABASE):
            (source / name).unlink(missing_ok=True)
        for folder in reversed(folders):
            (source / folder).rmdir()
