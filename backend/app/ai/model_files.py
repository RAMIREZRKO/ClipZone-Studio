"""Descarga de pesos oficiales y verificación independiente por modelo."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import errno
from functools import lru_cache
import hashlib
from http.client import HTTPException, IncompleteRead
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import shutil
import socket
import ssl
import stat
from threading import Event, RLock
from tempfile import NamedTemporaryFile
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

MODEL_HASHES = {
    "tiny": "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9",
    "base": "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e",
    "small": "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794",
}
MODEL_BYTES = {"tiny": 75572083, "base": 145262807, "small": 483617219}
BLOCK_SIZE = 1024 * 1024
RETRY_DELAYS = (1, 3)
TIMEOUT = 45
logger = logging.getLogger(__name__)


class DownloadCancelled(Exception):
    pass


class DownloadError(ValueError):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def create_diagnostic_logger(path: Path) -> logging.Logger:
    diagnostics = logging.Logger("clipzone.whisper.download")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    except OSError:
        logger.warning("No se pudo abrir el registro de Whisper en %s", path, exc_info=True)
        return logger
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    diagnostics.addHandler(handler)
    return diagnostics


def close_diagnostic_logger(diagnostics: logging.Logger):
    if diagnostics is not logger:
        for handler in diagnostics.handlers[:]:
            diagnostics.removeHandler(handler)
            handler.close()


def signature(metadata):
    return metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns, metadata.st_ino


@lru_cache(maxsize=24)
def file_sha256(path: Path, fingerprint: tuple) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(BLOCK_SIZE):
            digest.update(block)
    if signature(path.stat()) != fingerprint:
        raise OSError("El archivo cambió mientras se calculaba su SHA-256.")
    return digest.hexdigest()


def inspect_model(model: str, folder: Path) -> tuple[str, str | None]:
    path = folder / f"{model}.pt"
    try:
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            return "invalid", None
        digest = file_sha256(path, signature(metadata))
    except FileNotFoundError:
        return "missing", None
    except OSError:
        return "unreadable", None
    return ("verified" if digest == MODEL_HASHES[model] else "invalid"), digest


def network_error(error: Exception) -> DownloadError:
    if isinstance(error, HTTPError):
        retryable = error.code in (408, 425, 429) or 500 <= error.code < 600
        return DownloadError("http", f"El servidor de Whisper respondió HTTP {error.code}.", retryable)
    cause = error.reason if isinstance(error, URLError) else error
    if isinstance(cause, socket.gaierror):
        return DownloadError("dns", "DNS no pudo resolver openaipublic.azureedge.net. Comprueba la conexión y vuelve a intentar.", True)
    if isinstance(cause, TimeoutError):
        return DownloadError("timeout", "El servidor de Whisper tardó demasiado en responder. Vuelve a intentar.", True)
    if isinstance(cause, ssl.SSLError):
        return DownloadError("tls", "No se pudo establecer la conexión segura (TLS) con el servidor de Whisper.")
    if isinstance(cause, IncompleteRead):
        return DownloadError("incomplete", "La descarga terminó antes de recibir el modelo completo.", True)
    return DownloadError("connection", "Se interrumpió la conexión con el servidor de Whisper. Vuelve a intentar.", True)


def local_error(error: OSError) -> DownloadError:
    if error.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)) or getattr(error, "winerror", None) in (39, 112):
        return DownloadError("disk_full", "No hay espacio suficiente en la unidad de la carpeta de modelos.")
    if getattr(error, "winerror", None) in (32, 33):
        return DownloadError("locked", "Windows bloqueó el archivo del modelo. Cierra el programa que lo está usando y reintenta.")
    if isinstance(error, PermissionError):
        return DownloadError("permission", "ClipZone no tiene permiso para leer o escribir en la carpeta de modelos.")
    return DownloadError("filesystem", "No se pudo leer, guardar o publicar el modelo en la carpeta local. Consulta el registro.")


def check_cancelled(cancelled):
    if cancelled():
        raise DownloadCancelled()


def wait_to_retry(delay, cancelled):
    until = time.monotonic() + delay
    while (remaining := until - time.monotonic()) > 0:
        check_cancelled(cancelled)
        time.sleep(min(.1, remaining))


def receive_model(url, partial, folder, model, progress, cancelled, diagnostics):
    received = 0
    try:
        source = urlopen(url, timeout=TIMEOUT)
    except (OSError, HTTPException) as error:
        raise network_error(error) from error
    with source:
        length = source.headers.get("Content-Length", "")
        advertised_length = int(length) if length.isdecimal() else None
        total = advertised_length if advertised_length is not None else MODEL_BYTES[model]
        diagnostics.info("Respuesta model=%s status=%s content_length=%s esperado=%s",
                         model, getattr(source, "status", None), advertised_length, total)
        if getattr(source, "status", None) == 206:
            raise DownloadError("incomplete", "El servidor envió solo una parte del modelo.", True)
        if shutil.disk_usage(folder).free < total:
            raise DownloadError("disk_full", "No hay espacio suficiente en la unidad de la carpeta de modelos.")
        progress(0, total)
        with partial.open("wb") as output:
            while True:
                check_cancelled(cancelled)
                try:
                    block = source.read(BLOCK_SIZE)
                except (OSError, HTTPException) as error:
                    raise network_error(error) from error
                if not block:
                    break
                received += len(block)
                if received > total:
                    raise DownloadError("size", "El servidor envió más datos de los esperados para este modelo.")
                output.write(block)
                progress(received, total)
        if total != received:
            raise DownloadError("incomplete", f"Descarga incompleta: {received:,} de {total:,} bytes recibidos.", True)
    check_cancelled(cancelled)
    actual = file_sha256(partial, signature(partial.stat()))
    if actual != MODEL_HASHES[model]:
        diagnostics.warning("SHA256 incorrecto model=%s expected=%s actual=%s bytes=%s", model, MODEL_HASHES[model], actual, received)
        raise DownloadError("checksum", "El SHA256 del archivo recibido no coincide con el modelo oficial. El archivo no se instaló.")
    return received, actual


def download_model(
    model: str, folder: Path, progress=lambda received, total: None, cancelled=lambda: False,
    publish_lock=None, diagnostics=logger,
) -> Path:
    folder = folder.resolve()
    target = folder / f"{model}.pt"
    expected = MODEL_HASHES[model]
    diagnostics.info("Inicio model=%s dir=%s", model, folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        check_cancelled(cancelled)
        state, actual = inspect_model(model, folder)
        if state == "verified":
            size = target.stat().st_size
            progress(size, size)
            diagnostics.info("Modelo existente verificado model=%s bytes=%s sha256=%s", model, size, actual)
            return target
        if state == "unreadable":
            raise DownloadError("unreadable", "El archivo existente está bloqueado o no se puede leer. Cierra el programa que lo usa y reintenta.")
        if state == "invalid":
            if target.exists() and not target.is_file():
                raise DownloadError("filesystem", f"La ruta de {model}.pt existe y no es un archivo. Revisa la carpeta de modelos.")
            diagnostics.warning("Modelo local inválido model=%s sha256=%s", model, actual)

        url = f"https://openaipublic.azureedge.net/main/whisper/models/{expected}/{model}.pt"
        # A completed partial left by a process interruption is eligible for atomic publication.
        for leftover in sorted(folder.glob(f"{model}.*.part")):
            if leftover.is_symlink() or not leftover.is_file():
                continue
            try:
                metadata = leftover.stat()
                complete = metadata.st_size == MODEL_BYTES[model] and file_sha256(leftover, signature(metadata)) == expected
            except OSError:
                diagnostics.info("Temporal no disponible para recuperación model=%s", model, exc_info=True)
                continue
            if complete:
                with publish_lock if publish_lock is not None else nullcontext():
                    check_cancelled(cancelled)
                    if inspect_model(model, folder)[0] != "verified":
                        leftover.replace(target)
                progress(metadata.st_size, metadata.st_size)
                diagnostics.info("Modelo recuperado de temporal model=%s sha256=%s", model, expected)
                return target
            # Leave recent files alone in case another process is still writing them.
            if time.time() - metadata.st_mtime > 24 * 3600:
                try:
                    leftover.unlink()
                    diagnostics.info("Temporal antiguo retirado model=%s bytes=%s", model, metadata.st_size)
                except OSError:
                    diagnostics.warning("Temporal antiguo no se pudo retirar model=%s", model, exc_info=True)

        with NamedTemporaryFile(dir=folder, prefix=f"{model}.", suffix=".part", delete=False) as output:
            partial = Path(output.name)
        try:
            for attempt in range(len(RETRY_DELAYS) + 1):
                check_cancelled(cancelled)
                progress(0, None)
                diagnostics.info("Conexión model=%s intento=%s url=%s", model, attempt + 1, url)
                try:
                    received, actual = receive_model(url, partial, folder, model, progress, cancelled, diagnostics)
                    break
                except DownloadError as error:
                    if not error.retryable or attempt == len(RETRY_DELAYS):
                        raise
                    diagnostics.warning("Reintento model=%s intento=%s code=%s", model, attempt + 1, error.code, exc_info=True)
                    wait_to_retry(RETRY_DELAYS[attempt], cancelled)
            with publish_lock if publish_lock is not None else nullcontext():
                check_cancelled(cancelled)
                if inspect_model(model, folder)[0] != "verified":
                    partial.replace(target)
            diagnostics.info("Instalado model=%s bytes=%s sha256=%s", model, received, actual)
        finally:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                diagnostics.warning("El temporal quedó pendiente para el próximo intento model=%s path=%s", model, partial, exc_info=True)
        return target
    except OSError as error:
        raise local_error(error) from error


class ModelDownloads:
    def __init__(self, folder: Path, diagnostic_path: Path | None = None):
        self.folder = folder
        self.diagnostics = create_diagnostic_logger(diagnostic_path) if diagnostic_path else logger
        self.lock = RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipzone-model")
        self.entries: dict[str, dict] = {}
        self.current: tuple[str, Event] | None = None

    def statuses(self) -> dict:
        with self.lock:
            return {model: status.copy() for model, status in self.entries.items()}

    def start(self, model: str) -> dict:
        with self.lock:
            if self.current:
                if self.current[0] == model:
                    return self.entries[model].copy()
                raise ValueError("Ya hay un modelo descargándose. Espera o cancela esa descarga.")
            stop = Event()
            self.current = (model, stop)
            self.entries[model] = {"status": "downloading", "received": 0, "total": None, "error": None, "error_code": None}
            self.executor.submit(self._run, model, stop)
            return self.entries[model].copy()

    def _run(self, model: str, stop: Event):
        def progress(received, total):
            with self.lock:
                self.entries[model].update(received=received, total=total)

        status, error, error_code = "completed", None, None
        try:
            download_model(model, self.folder, progress, stop.is_set, self.lock, self.diagnostics)
        except DownloadCancelled:
            status = "cancelled"
        except Exception as exc:
            if stop.is_set():
                status = "cancelled"
            else:
                status = "failed"
                error = str(exc) if isinstance(exc, DownloadError) else "Error inesperado al instalar el modelo. Consulta el registro de diagnóstico."
                error_code = exc.code if isinstance(exc, DownloadError) else "unexpected"
                self.diagnostics.error("Fallo model=%s code=%s", model, error_code, exc_info=True)
        finally:
            with self.lock:
                self.entries[model].update(status=status, error=error, error_code=error_code)
                current = self.entries[model]
                self.diagnostics.info("Fin model=%s status=%s bytes=%s total=%s", model, status, current["received"], current["total"])
                self.current = None

    def cancel(self, model: str):
        with self.lock:
            if self.current and self.current[0] == model:
                self.current[1].set()
                self.entries[model]["status"] = "cancelling"

    def shutdown(self):
        with self.lock:
            if self.current:
                self.current[1].set()
        self.executor.shutdown(wait=True)
        close_diagnostic_logger(self.diagnostics)
